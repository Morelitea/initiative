import { format } from 'date-fns';
import { CalendarIcon } from 'lucide-react';

import { cn } from '../../lib/utils';
import { Button } from './button';
import { Calendar } from './calendar';
import { Input } from './input';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

interface DateTimePickerProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  clearLabel?: string;
}

const formatForStorage = (date: Date) => format(date, "yyyy-MM-dd'T'HH:mm");

const applyTimeToDate = (date: Date, time: string) => {
  const [hours, minutes] = time.split(':').map((segment) => Number.parseInt(segment, 10));
  const next = new Date(date);
  next.setHours(Number.isFinite(hours) ? hours : 0);
  next.setMinutes(Number.isFinite(minutes) ? minutes : 0);
  next.setSeconds(0);
  next.setMilliseconds(0);
  return next;
};

export const DateTimePicker = ({
  id,
  value,
  onChange,
  disabled = false,
  placeholder = 'Pick a date and time',
  clearLabel = 'Clear',
}: DateTimePickerProps) => {
  const selectedDate = value ? new Date(value) : undefined;
  const timeValue = selectedDate ? format(selectedDate, 'HH:mm') : '';

  const handleSelectDate = (date: Date | undefined) => {
    if (!date) {
      onChange('');
      return;
    }
    const baseTime = selectedDate ? format(selectedDate, 'HH:mm') : format(new Date(), 'HH:mm');
    const next = applyTimeToDate(date, baseTime);
    onChange(formatForStorage(next));
  };

  const handleTimeChange = (nextTime: string) => {
    if (!selectedDate) {
      return;
    }
    const next = applyTimeToDate(selectedDate, nextTime);
    onChange(formatForStorage(next));
  };

  const handleClear = () => {
    onChange('');
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          className={cn(
            'w-full justify-start text-left font-normal',
            !selectedDate && 'text-muted-foreground'
          )}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {selectedDate ? format(selectedDate, 'PP p') : placeholder}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar mode="single" selected={selectedDate} onSelect={handleSelectDate} initialFocus />
        <div className="flex items-center gap-2 border-t p-3">
          <Input
            type="time"
            step={300}
            value={timeValue}
            onChange={(event) => handleTimeChange(event.target.value)}
            disabled={!selectedDate || disabled}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleClear}
            disabled={!selectedDate || disabled}
          >
            {clearLabel}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
};
