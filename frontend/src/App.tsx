import { Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider'
import { AppShell } from './components/AppShell'
import { Landing } from './pages/Landing'
import { Login } from './pages/Login'
import { Auctions } from './pages/Auctions'
import { NewAuction } from './pages/NewAuction'
import { AuctionDetail } from './pages/AuctionDetail'
import { Security } from './pages/Security'
import { AccountSecurity } from './pages/AccountSecurity'
import { Admin } from './pages/Admin'
import { NotFound } from './pages/NotFound'

export default function App() {
  return (
    <AuthProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/auctions" element={<Auctions />} />
          <Route path="/auctions/new" element={<NewAuction />} />
          <Route path="/auctions/:id" element={<AuctionDetail />} />
          <Route path="/security" element={<Security />} />
          <Route path="/account/security" element={<AccountSecurity />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AppShell>
    </AuthProvider>
  )
}