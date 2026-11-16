import '@fontsource-variable/roboto/wght.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/primitives.css';
import './styles/shell.css';
import './styles/components.css';
import './styles/home.css';
import './styles/web.css';

import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';

import {App} from './app/App';
import {detectLocale} from './i18n/i18n';

function sessionStorageOrNull(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root element');
createRoot(root).render(
  <StrictMode>
    <App
      locale={detectLocale(window.location.search, sessionStorageOrNull())}
    />
  </StrictMode>,
);
