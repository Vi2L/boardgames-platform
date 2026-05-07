import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        {/*
          richColors даёт раскраску по типу (success/error/warning/info).
          theme="dark" — соответствует общему оформлению; closeButton — для
          длинных сообщений (cURL-копи, ошибок).
        */}
        <Toaster
          richColors
          theme="dark"
          position="top-right"
          closeButton
          duration={4000}
        />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
