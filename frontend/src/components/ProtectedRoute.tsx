import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useServer } from "@/hooks/useServer";

export const ProtectedRoute = () => {
  const { token, loading } = useAuth();
  const { isNativePlatform } = useServer();

  if (loading) {
    return <p>Loading...</p>;
  }

  if (!token) {
    // On mobile, skip the landing page and go directly to login
    const redirectTo = isNativePlatform ? "/login" : "/welcome";
    return <Navigate to={redirectTo} replace />;
  }

  return <Outlet />;
};
