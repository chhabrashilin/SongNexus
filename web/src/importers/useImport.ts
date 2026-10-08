/** Runs an import in a Web Worker, with progress and cancel. */
import {useCallback, useEffect, useRef, useState} from 'react';

import type {FileOutcome, Progress} from './importFiles';
import type {WorkerResponse} from './worker';

export type ImportState =
  | {status: 'idle'}
  | {status: 'running'; progress: Progress}
  | {status: 'done'; outcomes: FileOutcome[]}
  | {status: 'failed'};

export function useImport() {
  const [state, setState] = useState<ImportState>({status: 'idle'});
  const worker = useRef<Worker | null>(null);

  const stop = useCallback(() => {
    worker.current?.terminate();
    worker.current = null;
  }, []);

  useEffect(() => stop, [stop]);

  const start = useCallback(
    (files: File[]) => {
      stop();
      const instance = new Worker(new URL('./worker.ts', import.meta.url), {
        type: 'module',
      });
      worker.current = instance;
      setState({
        status: 'running',
        progress: {done: 0, total: files.length, current: ''},
      });
      instance.onmessage = (event: MessageEvent<WorkerResponse>) => {
        const message = event.data;
        if (message.type === 'progress')
          setState({status: 'running', progress: message.progress});
        else if (message.type === 'done') {
          setState({status: 'done', outcomes: message.outcomes});
          stop();
        } else {
          setState({status: 'failed'});
          stop();
        }
      };
      instance.onerror = () => {
        setState({status: 'failed'});
        stop();
      };
      instance.postMessage({files});
    },
    [stop],
  );

  const cancel = useCallback(() => {
    stop();
    setState({status: 'idle'});
  }, [stop]);

  return {state, start, cancel, reset: cancel};
}
