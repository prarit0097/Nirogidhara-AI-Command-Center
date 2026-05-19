import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

function hasToken(): boolean {
  if (typeof window === "undefined") return false;
  const token = window.localStorage.getItem("nirogidhara.jwt");
  return Boolean(token);
}

interface RequireAuthProps {
  children: ReactNode;
}

export function RequireAuth({ children }: RequireAuthProps) {
  const [authed, setAuthed] = useState<boolean>(hasToken());
  const location = useLocation();

  useEffect(() => {
    function onCleared() {
      setAuthed(false);
    }
    window.addEventListener("nirogidhara:auth-cleared", onCleared);
    return () =>
      window.removeEventListener("nirogidhara:auth-cleared", onCleared);
  }, []);

  if (!authed) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <>{children}</>;
}

export default RequireAuth;
