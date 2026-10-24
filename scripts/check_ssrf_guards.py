#!/usr/bin/env python3
"""CI Guard: Verify that user-controlled URL fetch endpoints use SSRF protection."""
import ast
import os
import re
import sys

def check_integrations_upload_asset():
    with open("routers/integrations.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Verify runninghub_upload_asset uses safe_download_bytes
    fn_match = re.search(r"def runninghub_upload_asset\([^\)]*\):.*?(?=\n@|\Z)", content, re.DOTALL)
    if not fn_match:
        print("FAIL: runninghub_upload_asset not found in routers/integrations.py")
        return False
    body = fn_match.group(0)
    if "safe_download_bytes" not in body:
        print("FAIL: runninghub_upload_asset does not use safe_download_bytes")
        return False
    if "await client.get(source_url)" in body:
        print("FAIL: runninghub_upload_asset contains raw client.get(source_url)")
        return False
    return True

GUARD_FNS = {
    "safe_download_bytes",
    "safe_json_post",
    "assert_safe_peer_ip",
    "validate_safe_url",
    "is_safe_remote_url",
    "check_key_host_binding",
    "_check_host_not_metadata_or_link_local",
}
OUTBOUND_METHODS = ("get", "post", "put", "delete", "request", "stream")
TAINT_ATTRS = {"url", "source_url", "user_url", "remote_url", "image_url", "asset_url", "input_url"}
TAINT_PARAMS = {"url", "source_url", "user_url", "remote_url", "input_url", "target_url", "image_url", "asset_url", "host", "instance", "endpoint"}
STRING_METHODS = {"strip", "rstrip", "lstrip", "lower", "upper", "replace", "format", "split", "encode", "decode"}

class SSRFVisitor(ast.NodeVisitor):
    def __init__(self, filename, lines):
        self.filename = filename
        self.lines = lines
        self.errors = []
        self.tainted_vars = set()
        self.route_models = set()
        self.guarded_vars = set()
        self.guarded_attrs = set()
        self.dict_vars = set()
        self.http_client_vars = set()

    def _is_http_client_ctor(self, expr):
        if isinstance(expr, ast.Call):
            fn = expr.func
            if isinstance(fn, ast.Attribute) and fn.attr in ("AsyncClient", "Client", "Session"):
                return True
            if isinstance(fn, ast.Name) and fn.id in ("AsyncClient", "Client", "Session"):
                return True
        elif isinstance(expr, ast.Attribute) and expr.attr in ("AsyncClient", "Client", "Session"):
            return True
        elif isinstance(expr, ast.Name) and expr.id in ("httpx", "requests"):
            return True
        return False

    def _is_dict_ctor(self, expr):
        if isinstance(expr, ast.Call):
            fn = expr.func
            if isinstance(fn, ast.Name) and fn.id in ("dict", "defaultdict", "OrderedDict"):
                return True
            if isinstance(fn, ast.Attribute) and fn.attr in ("dict", "defaultdict", "OrderedDict"):
                return True
        return False

    def _expr_has_taint(self, expr):
        if expr is None:
            return False
        if isinstance(expr, ast.Constant):
            return False
        if isinstance(expr, ast.Name):
            if expr.id in self.route_models:
                return False
            return expr.id in self.tainted_vars and expr.id not in self.guarded_vars
        if isinstance(expr, ast.Attribute):
            attr_lower = expr.attr.lower()
            if attr_lower in STRING_METHODS:
                return self._expr_has_taint(expr.value)
            if attr_lower in TAINT_ATTRS or "url" in attr_lower or attr_lower in ("host", "instance", "endpoint", "target"):
                attr_str = ast.unparse(expr)
                if attr_str in self.guarded_attrs:
                    return False
                return True
            return False
        if isinstance(expr, ast.Call):
            fn_name = ""
            if isinstance(expr.func, ast.Name):
                fn_name = expr.func.id
            elif isinstance(expr.func, ast.Attribute):
                fn_name = expr.func.attr
            if fn_name in GUARD_FNS:
                return False
            if isinstance(expr.func, ast.Attribute) and expr.func.attr.lower() in STRING_METHODS:
                return self._expr_has_taint(expr.func.value)
            for arg in expr.args:
                if self._expr_has_taint(arg):
                    return True
            for kw in expr.keywords:
                if self._expr_has_taint(kw.value):
                    return True
            return False
        if isinstance(expr, ast.JoinedStr):
            for part in expr.values:
                if isinstance(part, ast.FormattedValue) and self._expr_has_taint(part.value):
                    return True
            return False
        if isinstance(expr, ast.BinOp):
            return self._expr_has_taint(expr.left) or self._expr_has_taint(expr.right)
        if isinstance(expr, ast.UnaryOp):
            return self._expr_has_taint(expr.operand)
        if isinstance(expr, ast.Subscript):
            if isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, str):
                s_val = expr.slice.value.lower()
                if s_val in TAINT_ATTRS or "url" in s_val or s_val in ("host", "instance", "endpoint", "target"):
                    return True
            return self._expr_has_taint(expr.value)
        return False

    def is_http_outbound_call(self, node):
        if not (isinstance(node.func, ast.Attribute) and node.func.attr in OUTBOUND_METHODS):
            return False
        caller = ""
        if isinstance(node.func.value, ast.Name):
            caller = node.func.value.id
        elif isinstance(node.func.value, ast.Attribute):
            caller = node.func.value.attr
        caller_lower = caller.lower()

        # Exclude known dictionaries tracked via AST assignment
        if caller in self.dict_vars:
            return False

        # Exclude standard dictionary / parameters / mapping / cache objects
        if caller_lower in ("os", "dict", "params", "data", "json", "headers", "request", "environ", "store"):
            return False
        if caller_lower.endswith(("_dict", "_map", "_cache", "_tasks", "_meta", "meta", "config", "store", "_store")):
            return False
        if caller.isupper():  # Constants like CANVAS_TASKS, CONFIG, etc.
            return False

        # Non-get methods on objects are always outbound HTTP
        if node.func.attr in ("post", "put", "delete", "request", "stream"):
            return True

        # .get() disambiguation based on dataflow, not caller name guessing
        if node.func.attr == "get":
            # 1. Receiver is a tracked HTTP client object or module
            if caller in self.http_client_vars or caller_lower in ("httpx", "requests"):
                return True
            # 2. Has HTTP keyword args
            if any(kw.arg in ("headers", "timeout", "params", "proxies", "stream", "auth", "cookies", "follow_redirects") for kw in node.keywords):
                return True
            # 3. First argument is tainted
            first_arg = node.args[0] if node.args else None
            if not first_arg and node.keywords:
                for kw in node.keywords:
                    if kw.arg in ("url", "src"):
                        first_arg = kw.value
                        break
            if first_arg and self._expr_has_taint(first_arg):
                return True
            return False
        return True

    def visit_FunctionDef(self, node):
        prev_tainted = set(self.tainted_vars)
        prev_route_models = set(self.route_models)
        prev_guarded = set(self.guarded_vars)
        prev_guarded_attrs = set(self.guarded_attrs)
        prev_dict_vars = set(self.dict_vars)
        prev_http_vars = set(self.http_client_vars)

        is_route = False
        for dec in node.decorator_list:
            dec_node = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(dec_node, ast.Attribute) and dec_node.attr in ("get", "post", "put", "delete", "patch", "api_route"):
                is_route = True
                break

        for arg in node.args.args:
            arg_name = arg.arg.lower()
            if arg.arg in ("request", "response", "background_tasks", "client", "db"):
                continue
            if is_route:
                if arg.arg in ("payload", "body", "data", "req", "input") or (arg.annotation and isinstance(arg.annotation, ast.Name) and (arg.annotation.id.endswith(("Payload", "Model", "Config", "Request", "Params")) or arg.annotation.id[0].isupper())):
                    self.route_models.add(arg.arg)
                elif arg_name in TAINT_PARAMS or arg_name.endswith("_url"):
                    self.tainted_vars.add(arg.arg)
            elif arg_name in TAINT_PARAMS or (arg_name.endswith("_url") and not arg_name.startswith("upstream_") and not arg_name.startswith("base_")):
                self.tainted_vars.add(arg.arg)

        self.generic_visit(node)
        self.tainted_vars = prev_tainted
        self.route_models = prev_route_models
        self.guarded_vars = prev_guarded
        self.guarded_attrs = prev_guarded_attrs
        self.dict_vars = prev_dict_vars
        self.http_client_vars = prev_http_vars

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_With(self, node):
        for item in node.items:
            if self._is_http_client_ctor(item.context_expr):
                if isinstance(item.optional_vars, ast.Name):
                    self.http_client_vars.add(item.optional_vars.id)
            elif isinstance(item.context_expr, (ast.Dict, ast.DictComp)) or self._is_dict_ctor(item.context_expr):
                if isinstance(item.optional_vars, ast.Name):
                    self.dict_vars.add(item.optional_vars.id)
        self.generic_visit(node)

    def visit_AsyncWith(self, node):
        self.visit_With(node)

    def visit_Assign(self, node):
        # Track dict assignments
        if isinstance(node.value, (ast.Dict, ast.DictComp)) or self._is_dict_ctor(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.dict_vars.add(target.id)

        # Track HTTP client assignments
        if self._is_http_client_ctor(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.http_client_vars.add(target.id)

        # If assigned a constant or safe format string without tainted vars, remove target from tainted
        is_safe_literal = False
        if isinstance(node.value, ast.Constant):
            is_safe_literal = True
        elif isinstance(node.value, ast.JoinedStr):
            has_taint = False
            for part in node.value.values:
                if isinstance(part, ast.FormattedValue) and self._expr_has_taint(part.value):
                    has_taint = True
                    break
            if not has_taint:
                is_safe_literal = True

        if is_safe_literal:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.tainted_vars.discard(target.id)

        is_guard_call = False
        if isinstance(node.value, ast.Call):
            fn = ""
            if isinstance(node.value.func, ast.Name):
                fn = node.value.func.id
            elif isinstance(node.value.func, ast.Attribute):
                fn = node.value.func.attr
            if fn in GUARD_FNS:
                is_guard_call = True
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.guarded_vars.add(target.id)

        if not is_safe_literal and not is_guard_call and self._expr_has_taint(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.tainted_vars.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            self.tainted_vars.add(elt.id)

        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value:
            if not isinstance(node.value, ast.Constant) and self._expr_has_taint(node.value):
                if isinstance(node.target, ast.Name):
                    self.tainted_vars.add(node.target.id)
        self.generic_visit(node)

    def _check_loop_target_taint(self, target):
        if isinstance(target, ast.Name):
            t_lower = target.id.lower()
            if "url" in t_lower or "endpoint" in t_lower or t_lower in TAINT_ATTRS or t_lower in TAINT_PARAMS:
                self.tainted_vars.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._check_loop_target_taint(elt)

    def _is_safe_iter(self, iter_node):
        if isinstance(iter_node, ast.Name) and iter_node.id.isupper():
            return True
        if isinstance(iter_node, (ast.List, ast.Tuple)):
            if all(isinstance(elt, ast.Constant) for elt in iter_node.elts):
                return True
        return False

    def visit_For(self, node):
        if not self._is_safe_iter(node.iter):
            self._check_loop_target_taint(node.target)
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.visit_For(node)

    def visit_Call(self, node):
        fn_name = ""
        if isinstance(node.func, ast.Name):
            fn_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            fn_name = node.func.attr

        if fn_name in GUARD_FNS:
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    self.guarded_vars.add(arg.id)
                elif isinstance(arg, ast.Attribute):
                    self.guarded_attrs.add(ast.unparse(arg))
            for kw in node.keywords:
                if isinstance(kw.value, ast.Name):
                    self.guarded_vars.add(kw.value.id)
                elif isinstance(kw.value, ast.Attribute):
                    self.guarded_attrs.add(ast.unparse(kw.value))

        if fn_name == "safe_download_bytes":
            for kw in node.keywords:
                if kw.arg == "allow_private" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self.errors.append((node.lineno, "safe_download_bytes called with allow_private=True"))

        if self.is_http_outbound_call(node):
            target_arg = node.args[0] if node.args else None
            if not target_arg and node.keywords:
                for kw in node.keywords:
                    if kw.arg in ("url", "src"):
                        target_arg = kw.value
                        break
            if target_arg and self._expr_has_taint(target_arg):
                expr_str = ast.unparse(target_arg)
                self.errors.append((node.lineno, f"Raw .{node.func.attr}() on unvalidated tainted expression {expr_str} without SSRF guard"))

        self.generic_visit(node)

def check_no_raw_user_url_fetch():
    """Scan all route and core files using AST visitor and regex patterns."""
    failed = False
    for search_dir in ("routers", "core"):
        for root, _, files in os.walk(search_dir):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8") as fp:
                    content = fp.read()
                try:
                    tree = ast.parse(content, filename=path)
                except SyntaxError as e:
                    print(f"FAIL: Syntax error parsing {path}: {e}")
                    failed = True
                    continue
                visitor = SSRFVisitor(path, content.splitlines(True))
                visitor.visit(tree)
                for lineno, msg in visitor.errors:
                    print(f"FAIL: {path}:{lineno} {msg}")
                    failed = True
    return not failed

def main():
    ok = True
    if not check_integrations_upload_asset():
        ok = False
    if not check_no_raw_user_url_fetch():
        ok = False
    if ok:
        print("SSRF guards check passed: All user-controlled outbound fetch points use safe_download_bytes/validation.")
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
