import { useEffect, useRef } from 'react';

import { queryClient } from '../lib/queryClient';
import { useAuth } from './useAuth';

const invalidateByKey = (key: string) => {
  void queryClient.invalidateQueries({
    predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[0] === key,
  });
};

export const useRealtimeUpdates = () => {
  const { token } = useAuth();
  const websocketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!token) {
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    const wsUrl = `${protocol}://${host}/api/v1/events/updates?token=${encodeURIComponent(token)}`;
    const websocket = new WebSocket(wsUrl);
    websocketRef.current = websocket;

    websocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { resource?: string };
        switch (payload.resource) {
          case 'task':
            invalidateByKey('tasks');
            break;
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

    return () => {
      websocket.close();
      websocketRef.current = null;
    };
  }, [token]);
};
