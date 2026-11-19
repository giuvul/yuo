// How big a path is planned: shorter, standard or deep. Lessons are written only as the learner gets close to
// them, so a longer plan costs nothing until then. For a path from the learner's own material the size follows
// the material, and the choice says how much of it to cover.
import { useLingui } from "@lingui/react/macro";
import { ChoiceCards, ui } from "./ui";

export type Depth = "short" | "standard" | "deep";

export function DepthField({
  value,
  onChange,
  material,
  isDisabled,
}: {
  value: Depth;
  onChange: (value: Depth) => void;
  /** a path from the learner's own material: the size follows how much there is */
  material?: boolean;
  isDisabled?: boolean;
}) {
  const { t } = useLingui();
  const choices = material
    ? [
        {
          value: "short" as const,
          label: t({ id: "depth.short", message: "Shorter" }),
          description: t({ id: "depth.material.short", message: "The core of your material, fewer lessons." }),
        },
        {
          value: "standard" as const,
          label: t({ id: "depth.standard", message: "Standard" }),
          description: t({ id: "depth.material.standard", message: "As much as your material holds." }),
        },
        {
          value: "deep" as const,
          label: t({ id: "depth.deep", message: "Deep" }),
          description: t({ id: "depth.material.deep", message: "Every detail, with more lessons and practice." }),
        },
      ]
    : [
        {
          value: "short" as const,
          label: t({ id: "depth.short", message: "Shorter" }),
          description: t({ id: "depth.goal.short", message: "About 12 to 24 lessons: the essentials." }),
        },
        {
          value: "standard" as const,
          label: t({ id: "depth.standard", message: "Standard" }),
          description: t({ id: "depth.goal.standard", message: "About 40 to 70 lessons." }),
        },
        {
          value: "deep" as const,
          label: t({ id: "depth.deep", message: "Deep" }),
          description: t({ id: "depth.goal.deep", message: "About 80 to 120 lessons, every corner." }),
        },
      ];
  return (
    <div className={ui.stack}>
      <ChoiceCards
        label={t({ id: "depth.label", message: "How deep" })}
        choices={choices}
        value={value}
        onChange={onChange}
        compact
        isDisabled={isDisabled}
      />
      <p className={ui.muted}>
        {t({
          id: "depth.note",
          message: "Lessons are written as you get close to them, so a longer path costs nothing until you get there.",
        })}
      </p>
    </div>
  );
}
