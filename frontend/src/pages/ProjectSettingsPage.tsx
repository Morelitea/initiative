import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { apiClient } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { Project, ProjectRole, Team } from "../types/api";

export const ProjectSettingsPage = () => {
  const { projectId } = useParams();
  const parsedProjectId = Number(projectId);
  const navigate = useNavigate();
  const { user } = useAuth();
  const [readRoles, setReadRoles] = useState<ProjectRole[]>([]);
  const [writeRoles, setWriteRoles] = useState<ProjectRole[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<string>("");
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [teamMessage, setTeamMessage] = useState<string | null>(null);
  const [descriptionText, setDescriptionText] = useState<string>("");
  const [descriptionMessage, setDescriptionMessage] = useState<string | null>(
    null
  );

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

  const teamsQuery = useQuery<Team[]>({
    queryKey: ["teams"],
    enabled: user?.role === "admin",
    queryFn: async () => {
      const response = await apiClient.get<Team[]>("/teams/");
      return response.data;
    },
  });

  useEffect(() => {
    if (projectQuery.data) {
      setReadRoles(projectQuery.data.read_roles);
      setWriteRoles(projectQuery.data.write_roles);
      setSelectedTeamId(
        projectQuery.data.team_id ? String(projectQuery.data.team_id) : ""
      );
      setDescriptionText(projectQuery.data.description ?? "");
      setAccessMessage(null);
      setTeamMessage(null);
      setDescriptionMessage(null);
    }
  }, [projectQuery.data]);

  const updateAccess = useMutation({
    mutationFn: async () => {
      const response = await apiClient.patch<Project>(
        `/projects/${parsedProjectId}`,
        {
          read_roles: readRoles,
          write_roles: writeRoles,
        }
      );
      return response.data;
    },
    onSuccess: (data) => {
      setAccessMessage("Access settings updated");
      setReadRoles(data.read_roles);
      setWriteRoles(data.write_roles);
      void queryClient.invalidateQueries({
        queryKey: ["projects", parsedProjectId],
      });
    },
  });

  const updateTeamOwnership = useMutation({
    mutationFn: async () => {
      const payload = selectedTeamId
        ? { team_id: Number(selectedTeamId) }
        : { team_id: null };
      const response = await apiClient.patch<Project>(
        `/projects/${parsedProjectId}`,
        payload
      );
      return response.data;
    },
    onSuccess: (data) => {
      setTeamMessage("Project team updated");
      setSelectedTeamId(data.team_id ? String(data.team_id) : "");
      void queryClient.invalidateQueries({
        queryKey: ["projects", parsedProjectId],
      });
    },
  });

  const archiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/archive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["projects", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const updateDescription = useMutation({
    mutationFn: async () => {
      const response = await apiClient.patch<Project>(
        `/projects/${parsedProjectId}`,
        {
          description: descriptionText,
        }
      );
      return response.data;
    },
    onSuccess: (data) => {
      setDescriptionMessage("Description updated");
      setDescriptionText(data.description ?? "");
      void queryClient.invalidateQueries({
        queryKey: ["projects", parsedProjectId],
      });
    },
  });

  const unarchiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["projects", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const deleteProject = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/projects/${parsedProjectId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate("/");
    },
  });

  if (!Number.isFinite(parsedProjectId)) {
    return <p>Invalid project id.</p>;
  }

  const teamsLoading = user?.role === "admin" ? teamsQuery.isLoading : false;

  if (projectQuery.isLoading || teamsLoading) {
    return <p>Loading project settings...</p>;
  }

  if (projectQuery.isError || !projectQuery.data) {
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
  const userProjectRole = (user?.role as ProjectRole | undefined) ?? undefined;
  const canManageAccess =
    user?.role === "admin" ||
    membershipRole === "admin" ||
    membershipRole === "project_manager";
  const canWriteProject =
    user?.role === "admin" ||
    (membershipRole ? project.write_roles.includes(membershipRole) : false) ||
    (userProjectRole ? project.write_roles.includes(userProjectRole) : false);

  const projectRoleOptions: ProjectRole[] = [
    "admin",
    "project_manager",
    "member",
  ];

  if (!canManageAccess && !canWriteProject) {
    return (
      <div className="page">
        <Link to={`/projects/${project.id}`}>← Back to project</Link>
        <h1>Project settings</h1>
        <p>You do not have permission to manage this project.</p>
      </div>
    );
  }

  return (
    <div className="page">
      <Link to={`/projects/${project.id}`}>← Back to project</Link>
      <h1>Project settings</h1>

      <div className="card" style={{ marginBottom: "2rem" }}>
        <h2>Description</h2>
        {canWriteProject ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              updateDescription.mutate();
            }}
            style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}
          >
            <textarea
              value={descriptionText}
              onChange={(event) => setDescriptionText(event.target.value)}
              rows={4}
            />
            <button
              className="primary"
              type="submit"
              disabled={updateDescription.isPending}
            >
              {updateDescription.isPending ? "Saving..." : "Save description"}
            </button>
            {descriptionMessage ? (
              <p style={{ color: "#2563eb" }}>{descriptionMessage}</p>
            ) : null}
          </form>
        ) : (
          <p>You need write access to edit the description.</p>
        )}
      </div>

      {project.team ? (
        <div className="card" style={{ marginBottom: "2rem" }}>
          <h2>Project team</h2>
          <p>{project.team.name}</p>
          {project.team.members.length ? (
            <ul>
              {project.team.members.map((member) => (
                <li key={member.id}>{member.full_name ?? member.email}</li>
              ))}
            </ul>
          ) : (
            <p>No team members yet.</p>
          )}
        </div>
      ) : null}

      {user?.role === "admin" ? (
        <div className="card" style={{ marginBottom: "2rem" }}>
          <h2>Team ownership</h2>
          <p>Select which team owns this project.</p>
          {teamsQuery.isError ? (
            <p>Unable to load teams.</p>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                updateTeamOwnership.mutate();
              }}
              style={{
                display: "flex",
                gap: "0.5rem",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <select
                value={selectedTeamId}
                onChange={(event) => setSelectedTeamId(event.target.value)}
              >
                <option value="">No team</option>
                {teamsQuery.data?.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name}
                  </option>
                ))}
              </select>
              <button
                className="primary"
                type="submit"
                disabled={updateTeamOwnership.isPending}
              >
                {updateTeamOwnership.isPending ? "Saving..." : "Save team"}
              </button>
              {teamMessage ? (
                <p style={{ color: "#2563eb" }}>{teamMessage}</p>
              ) : null}
            </form>
          )}
        </div>
      ) : null}

      {canManageAccess ? (
        <div className="card" style={{ marginBottom: "2rem" }}>
          <h2>Project access</h2>
          <p>Choose which project roles can read or update this project.</p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setAccessMessage(null);
              updateAccess.mutate();
            }}
            style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
          >
            <div>
              <strong>Read access</strong>
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                {projectRoleOptions.map((role) => (
                  <label key={`read-${role}`} style={{ display: "flex" }}>
                    <input
                      type="checkbox"
                      checked={readRoles.includes(role)}
                      onChange={() =>
                        setReadRoles((prev) =>
                          prev.includes(role)
                            ? prev.filter((value) => value !== role)
                            : [...prev, role]
                        )
                      }
                    />
                    <span style={{ marginLeft: "0.25rem" }}>
                      {role.replace("_", " ")}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <div>
              <strong>Write access</strong>
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                {projectRoleOptions.map((role) => (
                  <label key={`write-${role}`} style={{ display: "flex" }}>
                    <input
                      type="checkbox"
                      checked={writeRoles.includes(role)}
                      onChange={() =>
                        setWriteRoles((prev) =>
                          prev.includes(role)
                            ? prev.filter((value) => value !== role)
                            : [...prev, role]
                        )
                      }
                    />
                    <span style={{ marginLeft: "0.25rem" }}>
                      {role.replace("_", " ")}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            <button
              className="primary"
              type="submit"
              disabled={updateAccess.isPending}
            >
              {updateAccess.isPending ? "Saving..." : "Save access"}
            </button>
            {accessMessage ? (
              <p style={{ color: "#2563eb" }}>{accessMessage}</p>
            ) : null}
          </form>
        </div>
      ) : null}

      <div className="card" style={{ marginBottom: "2rem" }}>
        <h2>Archive status</h2>
        <p>
          {project.is_archived
            ? "This project is archived."
            : "This project is active."}
        </p>
        {canWriteProject ? (
          <button
            className="secondary"
            type="button"
            onClick={() =>
              project.is_archived
                ? unarchiveProject.mutate()
                : archiveProject.mutate()
            }
            disabled={archiveProject.isPending || unarchiveProject.isPending}
          >
            {project.is_archived ? "Unarchive project" : "Archive project"}
          </button>
        ) : null}
      </div>

      {user?.role === "admin" ? (
        <div
          className="card"
          style={{ borderColor: "#dc2626", color: "#dc2626" }}
        >
          <h2>Danger zone</h2>
          <p>Deleting a project removes all of its tasks permanently.</p>
          <button
            className="secondary"
            type="button"
            onClick={() => {
              if (
                window.confirm("Delete this project? This cannot be undone.")
              ) {
                deleteProject.mutate();
              }
            }}
            disabled={deleteProject.isPending}
            style={{ borderColor: "#dc2626", color: "#dc2626" }}
          >
            Delete project
          </button>
        </div>
      ) : null}
    </div>
  );
};
