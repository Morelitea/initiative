import { useEffect, useRef } from 'react';

import { API_BASE_URL } from '../api/client';
import { queryClient } from '../lib/queryClient';
import { useAuth } from './useAuth';

const invalidateByKey = (key: string) => {
  void queryClient.invalidateQueries({
    queryKey: [key],
    exact: false,
  });
};

const invalidateProjectById = (projectId: unknown) => {
  if (typeof projectId !== 'number') {
    return;
  }
  void queryClient.invalidateQueries({ queryKey: ['projects', projectId] });
};

const buildWebsocketUrl = (token: string) => {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const base =
      API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')
        ? new URL(API_BASE_URL)
        : new URL(API_BASE_URL, window.location.origin);

    const normalizedPath = base.pathname.endsWith('/')
      ? base.pathname.slice(0, -1)
      : base.pathname || '/api/v1';

    base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
    base.pathname = `${normalizedPath}/events/updates`;
    base.search = '';
    base.hash = '';
    base.searchParams.set('token', token);
    return base.toString();
  } catch {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${protocol}://${window.location.host}/api/v1/events/updates?token=${encodeURIComponent(token)}`;
  }
};

export const useRealtimeUpdates = () => {
  const { token } = useAuth();
  const websocketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!token) {
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      return;
    }

    let isActive = true;

    const scheduleReconnect = () => {
      if (!isActive || reconnectTimerRef.current !== null) {
        return;
      }
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, 2000);
    };

    const connect = () => {
      if (!isActive) {
        return;
      }
      const wsUrl = buildWebsocketUrl(token);
      if (!wsUrl) {
        scheduleReconnect();
        return;
      }
      const websocket = new WebSocket(wsUrl);
      websocketRef.current = websocket;

      websocket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { resource?: string; data?: Record<string, unknown> };
          switch (payload.resource) {
            case 'task': {
              invalidateByKey('tasks');
              invalidateProjectById(payload.data?.project_id);
              break;
            }
            case 'project':
              invalidateByKey('projects');
              break;
            default:
              break;
          }
        } catch {
          // ignore malformed messages
        }
      };

      websocket.onerror = () => {
        websocket.close();
      };

      websocket.onclose = () => {
        if (websocketRef.current === websocket) {
          websocketRef.current = null;
        }
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      isActive = false;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
    };
  }, [token]);
};
