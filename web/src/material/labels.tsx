import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { useLingui } from "@lingui/react/macro";
import { ChoiceField } from "../components/ui";
import type { Adherence, MaterialOut, MaterialRole } from "./api";

export const ADHERENCE: Record<Adherence, { label: MessageDescriptor; description: MessageDescriptor }> = {
  only: {
    label: msg({ id: "adherence.only", message: "Only my material" }),
    description: msg({
      id: "adherence.only.description",
      message: "Lessons and questions stay inside your files, in their words and notation. Best before an exam.",
    }),
  },
  grounded: {
    label: msg({ id: "adherence.grounded", message: "My material first" }),
    description: msg({
      id: "adherence.grounded.description",
      message: "Built on your files, with short explanations or examples added where they help (marked).",
    }),
  },
  open: {
    label: msg({ id: "adherence.open", message: "My material and beyond" }),
    description: msg({
      id: "adherence.open.description",
      message: "Your files set the topics; Yuo also teaches what they leave out.",
    }),
  },
};

export function AdherenceField({
  value,
  onChange,
  isDisabled,
}: {
  value: Adherence;
  onChange: (v: Adherence) => void;
  isDisabled?: boolean;
}) {
  const { t, i18n } = useLingui();
  return (
    <ChoiceField
      label={t({ id: "studies.course.adherence", message: "How closely to follow the material" })}
      choices={(Object.keys(ADHERENCE) as Adherence[]).map((k) => ({
        value: k,
        label: i18n._(ADHERENCE[k].label),
        description: i18n._(ADHERENCE[k].description),
      }))}
      value={value}
      onChange={onChange}
      isDisabled={isDisabled}
      stacked
    />
  );
}

export const ROLE: Record<MaterialRole, MessageDescriptor> = {
  textbook: msg({ id: "material.role.textbook", message: "Book" }),
  slides: msg({ id: "material.role.slides", message: "Slides" }),
  lecture: msg({ id: "material.role.lecture", message: "Recorded lecture" }),
  notes: msg({ id: "material.role.notes", message: "Notes" }),
  exercises: msg({ id: "material.role.exercises", message: "Exercises" }),
  exams: msg({ id: "material.role.exams", message: "Past exams" }),
  other: msg({ id: "material.role.other", message: "Other" }),
};

export const STATE: Record<MaterialOut["state"], MessageDescriptor> = {
  uploading: msg({ id: "material.state.uploading", message: "Uploading" }),
  reading: msg({ id: "material.state.reading", message: "Reading" }),
  read: msg({ id: "material.state.read", message: "Read" }),
  transcribing: msg({ id: "material.state.transcribing", message: "Transcribing" }),
  digesting: msg({ id: "material.state.digesting", message: "Summarising" }),
  outlining: msg({ id: "material.state.outlining", message: "Finding the topics" }),
  ready: msg({ id: "material.state.ready", message: "Ready" }),
  failed: msg({ id: "material.state.failed", message: "Could not be read" }),
};

export const AWAITS_TRANSCRIPTION = msg({ id: "material.state.queued", message: "Waiting to be transcribed" });
