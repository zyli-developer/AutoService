import { useOperatorStore } from './store/operatorStore';
import { LoginPage } from './components/LoginPage';
import { WorkspacePage } from './components/WorkspacePage';

export function App() {
  const isLoggedIn = useOperatorStore((s) => s.isLoggedIn);
  return isLoggedIn ? <WorkspacePage /> : <LoginPage />;
}
