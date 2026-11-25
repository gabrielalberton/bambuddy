import { PenTool } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { plotter } from './api';

export const plotterNavItem = { id: 'plotter', to: '/plotter', icon: PenTool, labelKey: 'nav.penPlotter' };

export function usePlotterConfig(allowed = true) {
  return useQuery({
    queryKey: ['custom', 'plotter', 'config'],
    queryFn: plotter.config,
    enabled: allowed && import.meta.env.MODE !== 'test',
    staleTime: 60_000,
    retry: false,
  });
}
