import { BrowserRouter, Navigate, Route, Routes, useSearchParams } from 'react-router-dom';
import Workspace from './components/workspace/Workspace';
import Landing from './components/landing/Landing';

// Old shared links were `/?job=...`; keep them working by redirecting to /upload.
function RootRoute() {
  const [params] = useSearchParams();
  const job = params.get('job');
  if (job) return <Navigate to={`/upload?${params.toString()}`} replace />;
  return <Landing />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RootRoute />} />
        <Route path="/upload" element={<Workspace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
