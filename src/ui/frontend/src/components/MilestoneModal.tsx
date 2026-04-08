import type { MilestoneInfo } from "../api/types";
import { approveMilestone } from "../api/client";

interface Props {
  milestone: MilestoneInfo;
  onResolved: () => void;
}

export default function MilestoneModal({ milestone, onResolved }: Props) {
  const handleApprove = async (cont: boolean) => {
    await approveMilestone(cont);
    onResolved();
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
        <h3 className="text-lg font-bold text-purple-700 mb-2">
          Milestone: {milestone.milestone_name}
        </h3>
        <p className="text-sm text-gray-600 mb-3">
          Chapter {milestone.chapter_number} &mdash; {milestone.structural_phase}
        </p>
        <div className="mb-4">
          <p className="text-sm font-medium mb-1">Phase constraints:</p>
          <ul className="text-sm text-gray-600 space-y-1">
            {milestone.constraints.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-gray-400">&bull;</span>
                {c}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex gap-3 justify-end">
          <button
            onClick={() => handleApprove(false)}
            className="px-4 py-2 text-sm rounded bg-gray-200 hover:bg-gray-300"
          >
            Abort Pipeline
          </button>
          <button
            onClick={() => handleApprove(true)}
            className="px-4 py-2 text-sm rounded bg-purple-600 text-white hover:bg-purple-700"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
}
