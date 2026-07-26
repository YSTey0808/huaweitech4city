import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Spinner from './Spinner'

// Gate for authenticated-only routes: logged-out users are sent to /login.
export default function ProtectedRoute() {
  const { session, loading } = useAuth()

  if (loading) return <Spinner />
  if (!session) return <Navigate to="/login" replace />
  return <Outlet />
}
