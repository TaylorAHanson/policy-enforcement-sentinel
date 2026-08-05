import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import './index.css';

// The outer boundary catches failures in the chrome itself — the sidebar, the
// enforcement banner, the router. Pages have their own boundary inside Layout,
// which keeps navigation usable when only one page is broken.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary label="The application failed to start">
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
