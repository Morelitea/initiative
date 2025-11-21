import { ChangeEvent, useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { apiClient } from '../api/client';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Avatar, AvatarFallback, AvatarImage } from '../components/ui/avatar';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { useAuth } from '../hooks/useAuth';
import type { User } from '../types/api';
import { toast } from 'sonner';

const dataUrl = (value?: string | null) => {
  if (!value) {
    return '';
  }
  if (value.startsWith('data:')) {
    return value;
  }
  return `data:image/png;base64,${value}`;
};

export const UserProfilePage = () => {
  const { user, refreshUser } = useAuth();
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [avatarMode, setAvatarMode] = useState<'upload' | 'url'>(user?.avatar_url ? 'url' : 'upload');
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar_url ?? '');
  const [avatarBase64, setAvatarBase64] = useState(user?.avatar_base64 ?? '');
  const [error, setError] = useState<string | null>(null);

  const avatarPreview = useMemo(() => {
    if (avatarMode === 'url') {
      return avatarUrl || user?.avatar_url || '';
    }
    return avatarBase64 || user?.avatar_base64 || '';
  }, [avatarMode, avatarUrl, avatarBase64, user?.avatar_url, user?.avatar_base64]);

  const updateProfile = useMutation({
    mutationFn: async () => {
      if (password && password !== confirmPassword) {
        throw new Error('Passwords do not match');
      }
      const payload: Record<string, unknown> = {};
      if (fullName !== user?.full_name) {
        payload.full_name = fullName;
      }
      if (password) {
        payload.password = password;
      }
      if (avatarMode === 'upload') {
        payload.avatar_base64 = avatarBase64 || null;
        payload.avatar_url = null;
      } else {
        payload.avatar_url = avatarUrl || null;
        payload.avatar_base64 = null;
      }
      await apiClient.patch<User>('/users/me', payload);
    },
    onSuccess: async () => {
      setPassword('');
      setConfirmPassword('');
      setError(null);
      await refreshUser();
      toast.success('Profile updated');
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : 'Unable to update profile');
    },
  });

  const handleAvatarUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      setAvatarMode('upload');
      setAvatarBase64(result);
    };
    reader.readAsDataURL(file);
  };

  if (!user) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">You need to be logged in to manage your profile.</p>
        <Button asChild variant="link" className="px-0">
          <Link to="/login">Go to login</Link>
        </Button>
      </div>
    );
  }

  const initials = (user.full_name ?? user.email ?? 'User')
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('') || 'PP';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Avatar className="h-16 w-16">
          {avatarPreview ? <AvatarImage src={dataUrl(avatarPreview)} alt={fullName || user.email} /> : null}
          <AvatarFallback>{initials}</AvatarFallback>
        </Avatar>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Profile settings</h1>
          <p className="text-sm text-muted-foreground">Keep your account details up to date.</p>
        </div>
      </div>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Personal info</CardTitle>
          <CardDescription>Update your name, password, and avatar.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-6"
            onSubmit={(event) => {
              event.preventDefault();
              updateProfile.mutate();
            }}
          >
            <div className="space-y-2">
              <Label>Email</Label>
              <Input value={user.email} disabled readOnly />
              <p className="text-xs text-muted-foreground">Email addresses cannot be changed.</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="full-name">Full name</Label>
              <Input
                id="full-name"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                placeholder="Your name"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="password">New password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm-password">Confirm password</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  placeholder="••••••••"
                />
              </div>
            </div>

            <div className="space-y-3">
              <Label>Avatar</Label>
              <Tabs value={avatarMode} onValueChange={(value) => setAvatarMode(value as 'upload' | 'url')}>
                <TabsList>
                  <TabsTrigger value="upload">Upload</TabsTrigger>
                  <TabsTrigger value="url">URL</TabsTrigger>
                </TabsList>
                <TabsContent value="upload" className="space-y-2">
                  <Input type="file" accept="image/*" onChange={handleAvatarUpload} />
                  {avatarBase64 ? (
                    <Button type="button" variant="ghost" size="sm" onClick={() => setAvatarBase64('')}>
                      Remove uploaded avatar
                    </Button>
                  ) : null}
                </TabsContent>
                <TabsContent value="url" className="space-y-2">
                  <Input
                    type="url"
                    placeholder="https://example.com/avatar.jpg"
                    value={avatarUrl}
                    onChange={(event) => setAvatarUrl(event.target.value)}
                  />
                  {avatarUrl ? (
                    <Button type="button" variant="ghost" size="sm" onClick={() => setAvatarUrl('')}>
                      Clear avatar URL
                    </Button>
                  ) : null}
                </TabsContent>
              </Tabs>
            </div>

            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={updateProfile.isPending}>
                {updateProfile.isPending ? 'Saving…' : 'Save changes'}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={updateProfile.isPending}
                onClick={() => {
                  setFullName(user.full_name ?? '');
                  setPassword('');
                  setConfirmPassword('');
                  setAvatarUrl(user.avatar_url ?? '');
                  setAvatarBase64(user.avatar_base64 ?? '');
                  setAvatarMode(user.avatar_url ? 'url' : 'upload');
                  setError(null);
                }}
              >
                Reset
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
