import { createContext, useContext } from "react";

export const AuthContext = createContext({ user: null, setUser: () => {} });

export function useAuth() {
  return useContext(AuthContext);
}
