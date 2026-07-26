import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Spinner from './Spinner'

// Gate for auth pages (/login, /signup): logged-in users are sent to the app.
export default function PublicOnlyRoute() {
  const { session, loading } = useAuth()

  if (loading) return <Spinner />
  if (session) return <Navigate to="/" replace />
  return <Outlet />
}
