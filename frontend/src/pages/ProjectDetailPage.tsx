import { FormEvent, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import { useAuth } from '../hooks/useAuth';
import { queryClient } from '../lib/queryClient';
import { Project, Task, TaskPriority, TaskStatus } from '../types/api';

const taskStatusOrder: TaskStatus[] = ['backlog', 'in_progress', 'blocked', 'done'];

const priorityVariant: Record<TaskPriority, 'default' | 'secondary' | 'destructive'> = {
  low: 'secondary',
  medium: 'default',
  high: 'default',
  urgent: 'destructive',
};

export const ProjectDetailPage = () => {
  const { projectId } = useParams();
  const parsedProjectId = Number(projectId);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<TaskPriority>('medium');
  const { user } = useAuth();

  const projectQuery = useQuery<Project>({
    queryKey: ['projects', parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${parsedProjectId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const tasksQuery = useQuery<Task[]>({
    queryKey: ['tasks', parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Task[]>('/tasks/', {
        params: { project_id: parsedProjectId },
      });
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const createTask = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<Task>('/tasks/', {
        project_id: parsedProjectId,
        title,
        description,
        priority,
      });
      return response.data;
    },
    onSuccess: () => {
      setTitle('');
      setDescription('');
      setPriority('medium');
      void queryClient.invalidateQueries({
        queryKey: ['tasks', parsedProjectId],
      });
    },
  });

  const updateTaskStatus = useMutation({
    mutationFn: async ({ taskId, status }: { taskId: number; status: TaskStatus }) => {
      const response = await apiClient.patch<Task>(`/tasks/${taskId}`, {
        status,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['tasks', parsedProjectId],
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
      <div className="space-y-4">
        <p className="text-destructive">Invalid project id.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  if (projectQuery.isLoading || tasksQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading project…</p>;
  }

  if (projectQuery.isError || tasksQuery.isError || !projectQuery.data) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">Unable to load project.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/">← Back to projects</Link>
        </Button>
      </div>
    );
  }

  const project = projectQuery.data;
  const membershipRole = project.members.find((member) => member.user_id === user?.id)?.role;
  const userProjectRole = (user?.role as 'admin' | 'project_manager' | 'member' | undefined) ?? undefined;
  const canManageSettings =
    user?.role === 'admin' || membershipRole === 'admin' || membershipRole === 'project_manager';
  const canWriteProject =
    user?.role === 'admin' ||
    (membershipRole ? project.write_roles.includes(membershipRole) : false) ||
    (userProjectRole ? project.write_roles.includes(userProjectRole) : false);
  const projectIsArchived = project.is_archived;

  return (
    <div className="space-y-6">
      <Button asChild variant="link" className="px-0">
        <Link to="/">← Back to projects</Link>
      </Button>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">{project.name}</h1>
        <Badge variant={projectIsArchived ? 'destructive' : 'secondary'}>
          {projectIsArchived ? 'Archived' : 'Active'}
        </Badge>
      </div>
      {project.description ? <p className="text-base text-muted-foreground">{project.description}</p> : null}
      {canManageSettings ? (
        <Button asChild variant="outline" className="w-fit">
          <Link to={`/projects/${project.id}/settings`}>Open project settings</Link>
        </Button>
      ) : null}
      {projectIsArchived ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          This project is archived. Unarchive it from settings to add or update tasks.
        </p>
      ) : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Create task</CardTitle>
          <CardDescription>Add work to the board. Only people with write access can create tasks.</CardDescription>
        </CardHeader>
        <CardContent>
          {projectIsArchived ? (
            <p className="text-sm text-muted-foreground">
              This project is archived. Unarchive it to add new tasks.
            </p>
          ) : canWriteProject ? (
            <form className="space-y-4" onSubmit={handleCreateTask}>
              <div className="space-y-2">
                <Label htmlFor="task-title">Title</Label>
                <Input
                  id="task-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="Draft launch plan"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="task-description">Description</Label>
                <Textarea
                  id="task-description"
                  rows={3}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Share context, links, or acceptance criteria."
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="task-priority">Priority</Label>
                <Select value={priority} onValueChange={(value) => setPriority(value as TaskPriority)}>
                  <SelectTrigger id="task-priority">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low priority</SelectItem>
                    <SelectItem value="medium">Medium priority</SelectItem>
                    <SelectItem value="high">High priority</SelectItem>
                    <SelectItem value="urgent">Urgent</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-2">
                <Button type="submit" disabled={createTask.isPending}>
                  {createTask.isPending ? 'Saving…' : 'Create task'}
                </Button>
                {createTask.isError ? <p className="text-sm text-destructive">Unable to create task.</p> : null}
              </div>
            </form>
          ) : (
            <p className="text-sm text-muted-foreground">You need write access to create tasks.</p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {taskStatusOrder.map((status) => (
          <Card key={status} className="shadow-sm">
            <CardHeader>
              <CardTitle className="text-lg capitalize">{status.replace('_', ' ')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {groupedTasks[status].length === 0 ? (
                <p className="text-sm text-muted-foreground">No tasks yet.</p>
              ) : (
                groupedTasks[status].map((task) => (
                  <div key={task.id} className="space-y-3 rounded-lg border bg-card p-3 shadow-sm">
                    <div>
                      <p className="font-medium">{task.title}</p>
                      {task.description ? (
                        <p className="text-sm text-muted-foreground">{task.description}</p>
                      ) : null}
                    </div>
                    <Badge variant={priorityVariant[task.priority]}>
                      Priority: {task.priority.replace('_', ' ')}
                    </Badge>
                    <div className="flex flex-wrap gap-2">
                      {taskStatusOrder
                        .filter((nextStatus) => nextStatus !== task.status)
                        .map((nextStatus) => (
                          <Button
                            key={nextStatus}
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => updateTaskStatus.mutate({ taskId: task.id, status: nextStatus })}
                            disabled={updateTaskStatus.isPending || projectIsArchived || !canWriteProject}
                          >
                            Move to {nextStatus.replace('_', ' ')}
                          </Button>
                        ))}
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};
