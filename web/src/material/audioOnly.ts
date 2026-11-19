// A recorded lecture's video is never kept: Yuo needs only its speech. For MP4 and MOV files, the most common,
// the audio track is copied out here, in the browser, before the upload (no re-encoding, a few seconds), so a
// 70 MB video sends about 10 MB. Anything else, or anything that goes wrong, uploads the file as it is.

import type { ISOFile, Movie } from "mp4box";

const VIDEO = /\.(mp4|m4v|mov)$/i;
const MIN_BYTES = 4 * 1024 * 1024; // smaller videos are not worth the work
const CHUNK = 4 * 1024 * 1024;

/** Whether `audioOnly` may make the file smaller. */
export function hasSeparableAudio(file: File, minBytes = MIN_BYTES): boolean {
  return VIDEO.test(file.name) && file.size >= minBytes;
}

/**
 * The audio track of an MP4 or MOV video, as an .m4a file with the same name; null when the file has none or
 * cannot be read this way (then the original is uploaded).
 */
export async function audioOnly(file: File, minBytes = MIN_BYTES): Promise<File | null> {
  if (!hasSeparableAudio(file, minBytes)) return null;
  try {
    const { createFile, MP4BoxBuffer } = await import("mp4box");
    const parts = await extract(file, createFile(), (ab, at) => MP4BoxBuffer.fromArrayBuffer(ab, at));
    if (!parts) return null;
    const out = new File(parts, file.name.replace(VIDEO, ".m4a"), { type: "audio/mp4", lastModified: file.lastModified });
    return out.size < file.size ? out : null;
  } catch {
    return null;
  }
}

async function extract(
  file: File,
  mp4: ISOFile,
  wrap: (ab: ArrayBuffer, at: number) => Parameters<ISOFile["appendBuffer"]>[0],
): Promise<BlobPart[] | null> {
  const parts: BlobPart[] = [];
  let failed = false;
  let ready = false;
  let finished = false;
  let jump: number | null = null; // once the index is read: back to the first sample, the audio is read from there
  mp4.onError = () => {
    failed = true;
  };
  mp4.onReady = (info: Movie) => {
    ready = true;
    const track = info.audioTracks[0];
    if (!track) {
      failed = true;
      return;
    }
    mp4.setSegmentOptions(track.id, null, { nbSamples: 500 });
    parts.push(mp4.initializeSegmentation().buffer);
    jump = mp4.seek(0, true).offset; // before start: each sample is sent once
    mp4.start();
  };
  mp4.onSegment = (id: number, _user: unknown, buffer: ArrayBuffer, nextSample: number, last: boolean) => {
    parts.push(buffer);
    mp4.releaseUsedSamples(id, nextSample);
    if (last) finished = true;
  };
  let next = 0;
  let reads = 0;
  const most = 3 * Math.ceil(file.size / CHUNK) + 10;
  while (!failed && !finished && next < file.size && reads++ < most) {
    const at = next;
    const ab = await file.slice(at, at + CHUNK).arrayBuffer();
    // mp4box answers where it wants to read next: past the video data to an index at the file's end, say
    const wanted = mp4.appendBuffer(wrap(ab, at), at + ab.byteLength >= file.size);
    if (jump !== null) {
      next = jump;
      jump = null;
    } else next = typeof wanted === "number" && wanted > at ? wanted : at + ab.byteLength;
  }
  mp4.flush();
  return !failed && ready && parts.length > 1 ? parts : null;
}
