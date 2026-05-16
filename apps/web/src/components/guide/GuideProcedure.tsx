import type { Guide } from "@/lib/types";
import { GuideStep } from "./GuideStep";

interface GuideProcedureProps {
    steps: Guide["steps"];
}

export function GuideProcedure({ steps }: GuideProcedureProps) {
    if (steps.length === 0) {
        return (
            <p className="text-sm text-muted-foreground">No steps defined.</p>
        );
    }

    return (
        <div className="flex flex-col gap-0">
            {steps.map((step, i) => (
                <GuideStep key={step.id} step={step} index={i} />
            ))}
        </div>
    );
}
