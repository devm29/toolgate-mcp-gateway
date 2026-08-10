"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, fetchSession, type AuditQuery, type ToolQuery } from "@/lib/api";

export const keys = {
  overview: ["overview"] as const,
  upstreams: ["upstreams"] as const,
  tools: (q: ToolQuery) => ["tools", q] as const,
  tool: (id: string) => ["tool", id] as const,
  toolDiff: (id: string) => ["tool-diff", id] as const,
  approvals: ["approvals"] as const,
  policies: ["policies"] as const,
  audit: (f: AuditQuery) => ["audit", f] as const,
  principals: ["principals"] as const,
  session: ["session"] as const,
};

export function useOverview() {
  return useQuery({ queryKey: keys.overview, queryFn: api.overview, refetchInterval: 15_000 });
}

export function useUpstreams() {
  return useQuery({ queryKey: keys.upstreams, queryFn: api.upstreams, refetchInterval: 10_000 });
}

export function useTools(query: ToolQuery) {
  return useQuery({ queryKey: keys.tools(query), queryFn: () => api.tools(query), placeholderData: (prev) => prev });
}

export function useTool(id: string) {
  return useQuery({ queryKey: keys.tool(id), queryFn: () => api.tool(id), enabled: Boolean(id) });
}

export function useToolDiff(id: string, enabled: boolean) {
  return useQuery({ queryKey: keys.toolDiff(id), queryFn: () => api.toolDiff(id), enabled });
}

export function useApprovals() {
  return useQuery({ queryKey: keys.approvals, queryFn: api.approvals, refetchInterval: 10_000 });
}

export function usePolicies() {
  return useQuery({ queryKey: keys.policies, queryFn: api.policies });
}

export function useAuditLog(filters: AuditQuery) {
  return useInfiniteQuery({
    queryKey: keys.audit(filters),
    queryFn: ({ pageParam }) => api.audit({ ...filters, ...(pageParam ? { cursor: pageParam } : {}), limit: 50 }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useSession() {
  return useQuery({ queryKey: keys.session, queryFn: fetchSession, staleTime: 60_000 });
}

export function usePrincipals() {
  return useQuery({ queryKey: keys.principals, queryFn: api.principals });
}

export function useInvalidateRegistry() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["tools"] });
    void client.invalidateQueries({ queryKey: ["tool"] });
    void client.invalidateQueries({ queryKey: ["tool-diff"] });
    void client.invalidateQueries({ queryKey: keys.approvals });
    void client.invalidateQueries({ queryKey: keys.overview });
    void client.invalidateQueries({ queryKey: keys.upstreams });
  };
}

export function useSyncUpstream() {
  const invalidate = useInvalidateRegistry();
  return useMutation({ mutationFn: (id: string) => api.syncUpstream(id), onSuccess: invalidate });
}
