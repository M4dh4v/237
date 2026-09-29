import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './design-system/tokens.css'
import './shell.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
