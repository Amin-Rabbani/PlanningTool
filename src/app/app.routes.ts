import { Routes } from '@angular/router';
import { DashboardComponent } from './dashboard.component';
import { SprintShellComponent } from './sprint-shell.component';

export const routes: Routes = [
  { path: '', component: DashboardComponent, title: 'اسپرینت‌ها | Sprint Room' },
  { path: 'sprint/:slug', component: SprintShellComponent, title: 'برنامه‌ریزی اسپرینت' },
  { path: '**', redirectTo: '' },
];
