import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClientModule } from '@angular/common/http';

// Material
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { BuyGuardianService, AnalysisResult, AnalysisError } from './services/buyguardian.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    HttpClientModule,
    MatToolbarModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatChipsModule,
    MatDividerModule,
    MatIconModule,
    MatTooltipModule,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private service = inject(BuyGuardianService);

  itemId = signal('');
  loading = signal(false);
  result = signal<AnalysisResult | null>(null);
  error = signal<AnalysisError | null>(null);
  detectedFromTab = signal(false);
  isProcessing = signal(false);

  ngOnInit(): void {
    this.detectFromCurrentTab();
  }

  /** Ask background.ts to get the itemId from the active OLX.ba tab */
  private detectFromCurrentTab(): void {
    if (!chrome?.runtime) return;

    chrome.runtime.sendMessage({ type: 'GET_CURRENT_ITEM' }, (response) => {
      if (chrome.runtime.lastError || !response?.itemId) return;
      
      this.itemId.set(response.itemId);
      this.detectedFromTab.set(true);
      
      // Auto-analyze on detection
      this.analyze(); 
    });
  }

  analyze(): void {
    const id = this.itemId().trim();
    if (!id) return;

    this.loading.set(true);
    this.isProcessing.set(false);
    this.result.set(null);
    this.error.set(null);

    this.service.analyze(id).subscribe({
      next: (data: AnalysisResult) => {
        this.result.set(data);
        this.loading.set(false);
        this.isProcessing.set(false);
      },
      error: (err: AnalysisError) => {
        this.error.set(err);
        this.loading.set(false);
        if (err.message.includes('obrađuje')) {
          this.isProcessing.set(true);
        }
      },
    });
  }

  getTrustColor(score: number | null): string {
    if (score === null || score === undefined) return 'trust-pending';
    if (score >= 8) return 'trust-high';
    if (score >= 5) return 'trust-medium';
    return 'trust-low';
  }

  getTrustLabel(score: number | null): string {
    if (score === null || score === undefined) return 'Računanje...';
    if (score >= 8) return 'Visok trust';
    if (score >= 5) return 'Srednji trust';
    return 'Nizak trust';
  }

  getRiskLabel(risk: string): string {
    return this.service.getRiskLabel(risk);
  }

  getPriceDiff(market: number, listing?: number): number | null {
    if (!listing || !market) return null;
    return Math.round(((listing - market) / market) * 100);
  }
}
