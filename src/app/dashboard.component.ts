import { AsyncPipe, DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { BehaviorSubject, catchError, finalize, map, of, shareReplay, switchMap } from 'rxjs';
import { SprintSummary } from './sprint.model';
import { SprintService } from './sprint.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [AsyncPipe, DatePipe, DecimalPipe, FormsModule, ReactiveFormsModule],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent implements OnInit {
  private readonly service = inject(SprintService);
  private readonly router = inject(Router);
  private readonly refresh$ = new BehaviorSubject<void>(undefined);

  readonly title = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.maxLength(80)],
  });
  readonly sprints$ = this.refresh$.pipe(
    switchMap(() =>
      this.service.list().pipe(
        map((result) => result.sprints),
        catchError(() => {
          this.loadError = 'دریافت فهرست اسپرینت‌ها ممکن نشد. مطمئن شوید برنامه با jira_proxy.py اجرا شده است.';
          return of([] as SprintSummary[]);
        }),
      ),
    ),
    shareReplay({ bufferSize: 1, refCount: true }),
  );

  dialogOpen = false;
  creating = false;
  createError = '';
  loadError = '';

  ngOnInit(): void {
    document.documentElement.dataset['surface'] = 'dashboard';
  }

  openCreate(): void {
    this.createError = '';
    this.title.setValue('');
    this.dialogOpen = true;
    setTimeout(() => document.getElementById('sprint-title')?.focus());
  }

  closeCreate(): void {
    if (!this.creating) this.dialogOpen = false;
  }

  createSprint(): void {
    this.title.markAsTouched();
    const value = this.title.value.trim();
    if (!value || this.title.invalid || this.creating) return;

    this.creating = true;
    this.createError = '';
    this.service
      .create(value)
      .pipe(finalize(() => (this.creating = false)))
      .subscribe({
        next: (sprint) => this.router.navigate(['/sprint', sprint.slug]),
        error: (error) => {
          this.createError = error?.error?.error || 'ساخت اسپرینت انجام نشد. دوباره تلاش کنید.';
        },
      });
  }

  openSprint(sprint: SprintSummary): void {
    this.router.navigate(['/sprint', sprint.slug]);
  }

  total(items: SprintSummary[], key: 'tasks' | 'members' | 'allocatedHours'): number {
    return items.reduce((sum, item) => sum + Number(item[key] || 0), 0);
  }

  progress(sprint: SprintSummary): number {
    return sprint.tasks ? Math.round((sprint.completedTasks / sprint.tasks) * 100) : 0;
  }

  capacityProgress(sprint: SprintSummary): number {
    return sprint.capacityHours
      ? Math.min(100, Math.round((sprint.allocatedHours / sprint.capacityHours) * 100))
      : 0;
  }

  trackSprint(_: number, sprint: SprintSummary): string {
    return sprint.slug;
  }
}
