import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    // The AudioWorklet processor runs in its own global scope.
    files: ['public/pcm-capture-worklet.js'],
    languageOptions: { globals: { AudioWorkletProcessor: 'readonly', registerProcessor: 'readonly' } },
  },
  {
    // Node's built-in test runner (`npm test`).
    files: ['src/**/*.test.js', 'src/voice/testHarness.js'],
    languageOptions: { globals: { ...globals.node } },
  },
])
