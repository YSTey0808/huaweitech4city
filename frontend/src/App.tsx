import { Routes, Route, Navigate } from 'react-router-dom'
import ProfilePage from './pages/ProfilePage'
import FriendsPage from './pages/FriendsPage'
import ChatPage from './pages/ChatPage'
import ReportsPage from './pages/ReportsPage'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import ProtectedRoute from './components/ProtectedRoute'
import PublicOnlyRoute from './components/PublicOnlyRoute'
import AppLayout from './components/AppLayout'

export default function App() {
  return (
    <Routes>
      {/* Auth pages — redirect to the app if already logged in. */}
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
      </Route>

      {/* Authenticated app — redirect to /login if logged out. */}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/chat" replace />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/friends" element={<FriendsPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:conversationId" element={<ChatPage />} />
          <Route path="/reports" element={<ReportsPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
