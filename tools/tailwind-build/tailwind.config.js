/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    '../../static/**/*.html',
    '../../static/js/**/*.js',
  ],
  safelist: [
    // R13-2: Safelist dynamic classes that might be constructed via JS template literals or runtime concatenation
    { pattern: /^(grid-cols|col-span|gap|w|h|p|px|py|m|mx|my|opacity)-[0-9.]+/ },
    { pattern: /^(flex|inline-flex|block|inline-block|hidden|truncate|relative|absolute)$/ },
    { pattern: /^(justify|items)-(start|end|center|between|around|stretch)$/ },
    { pattern: /^(bg|text|border)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-[0-9]+/ },
    'grid',
    'hidden',
    'block',
    'flex',
    'truncate',
    'w-full',
    'h-full',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
