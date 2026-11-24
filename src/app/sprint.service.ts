import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { SprintListResponse, SprintSummary } from './sprint.model';

@Injectable({ providedIn: 'root' })
export class SprintService {
  private readonly http = inject(HttpClient);

  list(): Observable<SprintListResponse> {
    return this.http.get<SprintListResponse>('/api/sprints');
  }

  create(title: string): Observable<SprintSummary> {
    return this.http.post<SprintSummary>('/api/sprints', { title });
  }
}
