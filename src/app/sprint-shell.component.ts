import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ActivatedRoute, Router } from '@angular/router';

@Component({
  selector: 'app-sprint-shell',
  standalone: true,
  templateUrl: './sprint-shell.component.html',
  styleUrl: './sprint-shell.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SprintShellComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);
  slug = '';
  frameUrl: SafeResourceUrl = '';

  ngOnInit(): void {
    this.slug = this.route.snapshot.paramMap.get('slug') || '';
    this.frameUrl = this.sanitizer.bypassSecurityTrustResourceUrl(`/planner.html?sprint=${encodeURIComponent(this.slug)}`);
    document.documentElement.dataset['surface'] = 'planner';
  }

  back(): void {
    this.router.navigate(['/']);
  }
}
