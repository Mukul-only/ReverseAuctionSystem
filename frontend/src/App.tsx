import { Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { Landing } from './pages/Landing'
import { Auctions } from './pages/Auctions'
import { Security } from './pages/Security'
import { NotFound } from './pages/NotFound'

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/auctions" element={<Auctions />} />
        <Route path="/security" element={<Security />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}