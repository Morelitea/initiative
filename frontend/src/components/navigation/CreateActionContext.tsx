import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

/**
 * A page's "primary create action" — what the app-wide bottom-nav add button
 * does on that route (e.g. open the create-task dialog on a project page).
 */
export type PrimaryCreateAction = {
  run: () => void;
};

type RegistryEntry = {
  id: string;
  /** `null` means "this route is a create context, but the user can't create here". */
  action: PrimaryCreateAction | null;
};

type RegisterApi = {
  register: (id: string, action: PrimaryCreateAction | null) => void;
  unregister: (id: string) => void;
};

type CreateActionState = {
  /** True when a create-able page is mounted (regardless of permission). */
  isCreateContext: boolean;
  /** The action to run, or `null` when the current context grants no permission. */
  action: PrimaryCreateAction | null;
};

// Split the stable register API from the derived state so pages that only
// register (and never read the state) don't re-render when the state changes.
const RegisterApiContext = createContext<RegisterApi | null>(null);
const CreateActionStateContext = createContext<CreateActionState>({
  isCreateContext: false,
  action: null,
});

export function CreateActionProvider({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<RegistryEntry[]>([]);

  const register = useCallback((id: string, action: PrimaryCreateAction | null) => {
    setEntries((prev) => {
      const rest = prev.filter((entry) => entry.id !== id);
      return [...rest, { id, action }];
    });
  }, []);

  const unregister = useCallback((id: string) => {
    setEntries((prev) => prev.filter((entry) => entry.id !== id));
  }, []);

  const api = useMemo<RegisterApi>(() => ({ register, unregister }), [register, unregister]);

  // The most recently registered page wins. In practice only one create-able
  // route is mounted at a time, so this is a single-slot lookup.
  const last = entries[entries.length - 1];
  const state = useMemo<CreateActionState>(
    () => ({ isCreateContext: entries.length > 0, action: last?.action ?? null }),
    [entries.length, last?.action]
  );

  return (
    <RegisterApiContext.Provider value={api}>
      <CreateActionStateContext.Provider value={state}>
        {children}
      </CreateActionStateContext.Provider>
    </RegisterApiContext.Provider>
  );
}

/**
 * Register the current route's primary create action with the bottom-nav add
 * button. Call this unconditionally from a create-able page (Rules of Hooks):
 * pass an action when the user may create here, or `null` when they can't (the
 * button is then hidden rather than falling back to the global create menu).
 */
export function useRegisterPrimaryCreateAction(action: PrimaryCreateAction | null) {
  const id = useId();
  const api = useContext(RegisterApiContext);
  // Keep the latest action in a ref so the registered closure always runs the
  // current handler without re-registering on every render.
  const actionRef = useRef(action);
  actionRef.current = action;
  const available = action != null;

  useEffect(() => {
    if (!api) return;
    api.register(id, available ? { run: () => actionRef.current?.run() } : null);
    return () => api.unregister(id);
  }, [api, id, available]);
}

/** Read the currently-registered create action (for the bottom-nav add button). */
export function usePrimaryCreateAction(): CreateActionState {
  return useContext(CreateActionStateContext);
}
