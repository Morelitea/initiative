import { useMutation, useQuery } from "@tanstack/react-query";
import { FormEvent, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { apiClient } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { Project, Task, TaskPriority, TaskStatus } from "../types/api";

const taskStatusOrder: TaskStatus[] = [
  "backlog",
  "in_progress",
  "blocked",
  "done",
];

export const ProjectDetailPage = () => {
  const { projectId } = useParams();
  const parsedProjectId = Number(projectId);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const { user } = useAuth();

  const projectQuery = useQuery<Project>({
    queryKey: ["projects", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(
        `/projects/${parsedProjectId}`
      );
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const tasksQuery = useQuery<Task[]>({
    queryKey: ["tasks", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Task[]>("/tasks/", {
        params: { project_id: parsedProjectId },
      });
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const createTask = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<Task>("/tasks/", {
        project_id: parsedProjectId,
        title,
        description,
        priority,
      });
      return response.data;
    },
    onSuccess: () => {
      setTitle("");
      setDescription("");
      setPriority("medium");
      void queryClient.invalidateQueries({
        queryKey: ["tasks", parsedProjectId],
      });
    },
  });

  const updateTaskStatus = useMutation({
    mutationFn: async ({
      taskId,
      status,
    }: {
      taskId: number;
      status: TaskStatus;
    }) => {
      const response = await apiClient.patch<Task>(`/tasks/${taskId}`, {
        status,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["tasks", parsedProjectId],
      });
    },
  });

  const groupedTasks = useMemo(() => {
    const groups: Record<TaskStatus, Task[]> = {
      backlog: [],
      in_progress: [],
      blocked: [],
      done: [],
    };
    tasksQuery.data?.forEach((task) => {
      groups[task.status].push(task);
    });
    return groups;
  }, [tasksQuery.data]);

  const handleCreateTask = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createTask.mutate();
  };

  if (!Number.isFinite(parsedProjectId)) {
    return (
      <div>
        <p>Invalid project id.</p>
        <Link to="/">← Back to projects</Link>
      </div>
    );
  }

  if (projectQuery.isLoading || tasksQuery.isLoading) {
    return <p>Loading...</p>;
  }

  if (projectQuery.isError || tasksQuery.isError || !projectQuery.data) {
    return (
      <div>
        <p>Unable to load project.</p>
        <Link to="/">← Back to projects</Link>
      </div>
    );
  }

  const project = projectQuery.data;
  const membershipRole = project.members.find(
    (member) => member.user_id === user?.id
  )?.role;
  const userProjectRole =
    (user?.role as "admin" | "project_manager" | "member" | undefined) ??
    undefined;
  const canManageSettings =
    user?.role === "admin" ||
    membershipRole === "admin" ||
    membershipRole === "project_manager";
  const canWriteProject =
    user?.role === "admin" ||
    (membershipRole ? project.write_roles.includes(membershipRole) : false) ||
    (userProjectRole ? project.write_roles.includes(userProjectRole) : false);
  const projectIsArchived = project.is_archived;

  return (
    <div className="page">
      <Link to="/">← Back to projects</Link>
      <h1>{project.name}</h1>
      {project.description && <p>{project.description}</p>}
      {canWriteProject ? (
        <Link className="secondary" to={`/projects/${project.id}/settings`}>
          Open project settings →
        </Link>
      ) : null}
      {projectIsArchived ? (
        <p style={{ color: "#dc2626" }}>
          This project is archived. Unarchive it from the settings page to add
          or update tasks.
        </p>
      ) : null}

      <div className="card" style={{ marginBottom: "2rem" }}>
        <h2>Create task</h2>
        {projectIsArchived ? (
          <p>This project is archived. Unarchive it to add new tasks.</p>
        ) : (
          <form onSubmit={handleCreateTask}>
            <input
              placeholder="Title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
            />
            <textarea
              placeholder="Description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
            />
            <select
              value={priority}
              onChange={(event) =>
                setPriority(event.target.value as TaskPriority)
              }
            >
              <option value="low">Low priority</option>
              <option value="medium">Medium priority</option>
              <option value="high">High priority</option>
              <option value="urgent">Urgent</option>
            </select>
            <button
              className="primary"
              type="submit"
              disabled={createTask.isPending}
            >
              {createTask.isPending ? "Saving..." : "Create task"}
            </button>
            {createTask.isError ? (
              <p style={{ color: "tomato" }}>Unable to create task</p>
            ) : null}
          </form>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gap: "1rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        }}
      >
        {taskStatusOrder.map((status) => (
          <div className="card" key={status}>
            <h3 style={{ textTransform: "capitalize" }}>
              {status.replace("_", " ")}
            </h3>
            {groupedTasks[status].map((task) => (
              <div
                key={task.id}
                className="list-item"
                style={{ marginBottom: "0.5rem" }}
              >
                <strong>{task.title}</strong>
                <p>{task.description}</p>
                <p>Priority: {task.priority}</p>
                <div
                  style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}
                >
                  {taskStatusOrder
                    .filter((nextStatus) => nextStatus !== task.status)
                    .map((nextStatus) => (
                      <button
                        key={nextStatus}
                        className="secondary"
                        type="button"
                        onClick={() =>
                          updateTaskStatus.mutate({
                            taskId: task.id,
                            status: nextStatus,
                          })
                        }
                        disabled={
                          updateTaskStatus.isPending ||
                          projectIsArchived ||
                          !canWriteProject
                        }
                      >
                        Move to {nextStatus.replace("_", " ")}
                      </button>
                    ))}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
};
