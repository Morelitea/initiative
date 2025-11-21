import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';

interface InterfaceSettings {
  light_accent_color: string;
  dark_accent_color: string;
}

const clamp = (value: number) => Math.max(0, Math.min(100, value));

const hexToHsl = (hex: string) => {
  let normalized = hex.replace('#', '');
  if (normalized.length === 3) {
    normalized = normalized
      .split('')
      .map((char) => `${char}${char}`)
      .join('');
  }
  const bigint = parseInt(normalized, 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  const rNorm = r / 255;
  const gNorm = g / 255;
  const bNorm = b / 255;
  const max = Math.max(rNorm, gNorm, bNorm);
  const min = Math.min(rNorm, gNorm, bNorm);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case rNorm:
        h = (gNorm - bNorm) / d + (gNorm < bNorm ? 6 : 0);
        break;
      case gNorm:
        h = (bNorm - rNorm) / d + 2;
        break;
      case bNorm:
        h = (rNorm - gNorm) / d + 4;
        break;
    }
    h /= 6;
  }

  return {
    h: Math.round(h * 360),
    s: Math.round(s * 100),
    l: Math.round(l * 100),
  };
};

const hslToString = ({ h, s, l }: { h: number; s: number; l: number }) => `${h} ${s}% ${l}%`;

const lighten = (hsl: { h: number; s: number; l: number }, amount: number) => ({
  ...hsl,
  l: clamp(hsl.l + amount),
});

const darken = (hsl: { h: number; s: number; l: number }, amount: number) => ({
  ...hsl,
  l: clamp(hsl.l - amount),
});

const applyInterfaceColors = (settings: InterfaceSettings) => {
  const light = hexToHsl(settings.light_accent_color);
  const dark = hexToHsl(settings.dark_accent_color);
  const root = document.documentElement;
  root.style.setProperty('--accent-light-color', hslToString(light));
  root.style.setProperty('--accent-light-surface', hslToString(lighten(light, 30)));
  root.style.setProperty('--accent-dark-color', hslToString(dark));
  root.style.setProperty('--accent-dark-surface', hslToString(darken(dark, 35)));
};

export const useInterfaceColors = () => {
  const query = useQuery({
    queryKey: ['interface-settings'],
    queryFn: async () => {
      const response = await apiClient.get<InterfaceSettings>('/settings/interface');
      return response.data;
    },
    staleTime: 1000 * 60 * 10,
  });

  useEffect(() => {
    if (query.data) {
      applyInterfaceColors(query.data);
    }
  }, [query.data]);

  return query;
};
