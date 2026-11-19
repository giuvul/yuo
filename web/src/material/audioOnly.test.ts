import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { audioOnly, hasSeparableAudio } from "./audioOnly";

const video = readFileSync(`${__dirname}/fixtures/lecture.mp4`);

describe("a lecture video's audio, taken out before the upload", () => {
  it("is an .m4a with only the audio track, much smaller than the video", async () => {
    const out = await audioOnly(new File([video], "Lezione 3.mp4", { lastModified: 7 }), 0);
    expect(out).not.toBeNull();
    expect(out!.name).toBe("Lezione 3.m4a");
    expect(out!.type).toBe("audio/mp4");
    expect(out!.size).toBeLessThan(video.length / 2);
    const text = new TextDecoder("latin1").decode(await out!.arrayBuffer());
    expect(text.slice(4, 8)).toBe("ftyp");
    expect(text).toContain("mp4a"); // the AAC track
    expect(text).not.toContain("avcC"); // no video track (its codec setup)
    expect(text).toContain("moof");
  });

  it("leaves other files, small videos and unreadable ones as they are", async () => {
    expect(hasSeparableAudio(new File([video], "talk.mp4"))).toBe(false); // under 4 MB: not worth it
    expect(hasSeparableAudio(new File([video], "talk.webm"), 0)).toBe(false);
    expect(await audioOnly(new File([video], "talk.mkv"), 0)).toBeNull();
    expect(await audioOnly(new File([new Uint8Array(5000)], "broken.mp4"), 0)).toBeNull();
  });
});
