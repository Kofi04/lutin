/**
 * Data from the core (services.py), kept current.
 *
 * `reload()` asks again; `call()` runs a change and reports its refusal
 * (the core's French message) in `error` instead of throwing.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { CoreClient } from "../core/client";

export interface Requested<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload(): void;
}

export function useRequest<T>(
  client: CoreClient,
  /** null: nothing to ask yet (no selection). */
  method: string | null,
  params: Record<string, unknown> = {},
): Requested<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [round, setRound] = useState(0);
  const key = JSON.stringify(params);
  const latest = useRef(0);

  useEffect(() => {
    const ticket = ++latest.current;
    if (method === null) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    client
      .request<T>(method, JSON.parse(key) as Record<string, unknown>)
      .then((result) => {
        // An older answer arriving after a newer one (a search being typed)
        // must not replace it.
        if (ticket !== latest.current) return;
        setData(result);
        setError(null);
      })
      .catch((reason: Error) => {
        if (ticket === latest.current) setError(reason.message);
      })
      .finally(() => {
        if (ticket === latest.current) setLoading(false);
      });
  }, [client, method, key, round]);

  // Asked again when the core comes back: it may have been restarted.
  useEffect(
    () =>
      client.onStatus((status) => {
        if (status === "online") setRound((r) => r + 1);
      }),
    [client],
  );

  const reload = useCallback(() => setRound((r) => r + 1), []);
  return { data, error, loading, reload };
}

/** A change: resolves to the data, or null after showing the refusal. */
export function useCall(client: CoreClient) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const call = useCallback(
    async <T = Record<string, unknown>>(
      method: string,
      params: Record<string, unknown> = {},
    ): Promise<T | null> => {
      setBusy(true);
      try {
        const data = await client.request<T>(method, params);
        setError(null);
        return data;
      } catch (reason) {
        setError((reason as Error).message);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [client],
  );
  return { call, error, setError, busy };
}
