import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { tg } from './api.js'
import './styles.css'

try {
  tg?.ready()
  tg?.expand()
  // фон и шапка Telegram в цвет приложения (методы есть не во всех версиях клиента)
  tg?.setHeaderColor?.('secondary_bg_color')
  tg?.setBackgroundColor?.('secondary_bg_color')
} catch {
  /* старый клиент */
}

createRoot(document.getElementById('root')).render(<App />)
