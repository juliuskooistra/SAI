import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useAuth() {
  const { data: session, isLoading, error } = useQuery({
    queryKey: ['/api/session'],
    queryFn: api.getSession,
    retry: false,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  return {
    user: session?.user,
    isLoading,
    isAuthenticated: !!session?.user,
    error,
  };
}