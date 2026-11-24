export interface SprintSummary {
  slug: string;
  title: string;
  fileName: string;
  createdAt: string;
  updatedAt: string;
  startDate: string;
  endDate: string;
  members: number;
  tasks: number;
  completedTasks: number;
  allocatedHours: number;
  capacityHours: number;
}

export interface SprintListResponse {
  sprints: SprintSummary[];
}
