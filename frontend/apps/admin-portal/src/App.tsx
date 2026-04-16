import { useAdminStore } from './store/adminStore';
import { LoginPage } from './components/LoginPage';
import { AdminWorkspace } from './components/AdminWorkspace';

export function App() {
  const isLoggedIn = useAdminStore((s) => s.isLoggedIn);
  return isLoggedIn ? <AdminWorkspace /> : <LoginPage />;
}
