/// <reference lib="webworker" />
/**
 * The import Web Worker: parses files off the main thread, so the page stays
 * responsive even for 100 MB exports (plan §23). Cancel by terminating it.
 */
import {importFiles, type FileOutcome, type Progress} from './importFiles';

export type WorkerRequest = {files: File[]};
export type WorkerResponse =
  | {type: 'progress'; progress: Progress}
  | {type: 'done'; outcomes: FileOutcome[]}
  | {type: 'error'; message: string};

declare const self: DedicatedWorkerGlobalScope;

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  try {
    const outcomes = await importFiles(
      event.data.files.map(file => ({
        name: file.name,
        size: file.size,
        bytes: async () => new Uint8Array(await file.arrayBuffer()),
      })),
      progress =>
        self.postMessage({type: 'progress', progress} satisfies WorkerResponse),
    );
    self.postMessage({type: 'done', outcomes} satisfies WorkerResponse);
  } catch (error) {
    self.postMessage({
      type: 'error',
      message: String(error),
    } satisfies WorkerResponse);
  }
};
