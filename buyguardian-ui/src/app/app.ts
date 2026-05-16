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
import { MatSliderModule } from '@angular/material/slider';

import { BuyGuardianService, AnalysisResult, AnalysisError, Recommendation } from './services/buyguardian.service';

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
    MatSliderModule,
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
  recommendations = signal<Recommendation[]>([]);
  loadingRecs = signal(false);

  showSettings = signal(false);
  settingsApiUrl = signal('');
  scoreBreakdownOpen = signal(true);

  readonly listingWeight = 0.7;
  readonly sellerWeight = 0.3;
  readonly pricePenaltyMax = 2.0;

  customListingWeight = 40;
  customSellerWeight = 30;
  customPriceWeight = 30;

  async ngOnInit(): Promise<void> {
    this.settingsApiUrl.set(await this.service.getConfig());
    const weights = await this.service.getWeights();
    this.customListingWeight = weights.listing;
    this.customSellerWeight = weights.seller;
    this.customPriceWeight = weights.price;
    
    this.detectFromCurrentTab();
  }


  toggleSettings(): void {
    this.showSettings.update(v => !v);
  }

  async saveSettings(): Promise<void> {
    await this.service.saveConfig(this.settingsApiUrl());
    await this.service.saveWeights(
      this.customListingWeight,
      this.customSellerWeight,
      this.customPriceWeight
    );
    this.showSettings.set(false);
    // Reload if on item
    if (this.itemId()) {
      this.analyze();
    }
  }

  async revertToDefaultWeights(): Promise<void> {
    const defaults = { listing: 40, seller: 30, price: 30 };
    this.customListingWeight = defaults.listing;
    this.customSellerWeight = defaults.seller;
    this.customPriceWeight = defaults.price;
    await this.service.saveWeights(defaults.listing, defaults.seller, defaults.price);
    
    // Reload if on item to update display score
    if (this.itemId()) {
      this.analyzeQuietly();
    }
  }

  /** Ask background.ts to get the itemId from the active OLX.ba tab */
  private detectFromCurrentTab(): void {
    if (!chrome?.runtime) return;

    chrome.runtime.sendMessage({ type: 'GET_CURRENT_ITEM' }, async (response) => {
      if (chrome.runtime.lastError || !response?.itemId) return;
      
      this.itemId.set(response.itemId);
      this.detectedFromTab.set(true);
      
      // Try cached analysis first for instant display
      const cached = await this.service.getCachedAnalysis(response.itemId);
      if (cached) {
        this.result.set(cached);
        // Load recommendations from cache or fetch
        this.loadRecommendations(response.itemId);
        // Still refresh in background
        this.analyzeQuietly();
      } else {
        this.analyze();
      }
    });
  }

  /** Full analyze with loading state */
  async analyze(): Promise<void> {
    const id = this.itemId().trim();
    if (!id) return;

    this.loading.set(true);
    this.isProcessing.set(false);
    this.result.set(null);
    this.error.set(null);

    try {
      const data = await this.service.analyze(id);
      this.result.set(data);
      this.loading.set(false);
      this.isProcessing.set(false);
      this.loadRecommendations(id);
    } catch (err: any) {
      this.error.set(err as AnalysisError);
      this.loading.set(false);
      if (err.message?.includes('obrađuje')) {
        this.isProcessing.set(true);
      }
    }
  }

  /** Silent background refresh (no loading indicator) */
  private async analyzeQuietly(): Promise<void> {
    const id = this.itemId().trim();
    if (!id) return;

    try {
      const data = await this.service.analyze(id);
      this.result.set(data);
    } catch (e) {
      // Silent fail — we already have cached data
    }
  }

  /** Load recommendations from cache or API */
  private async loadRecommendations(itemId: string): Promise<void> {
    // Try cache first
    const cached = await this.service.getCachedRecommendations(itemId);
    if (cached && cached.length > 0) {
      this.recommendations.set(cached);
      return;
    }

    // Fetch from API
    this.loadingRecs.set(true);
    try {
      const recs = await this.service.getRecommendations(itemId);
      this.recommendations.set(recs);
    } finally {
      this.loadingRecs.set(false);
    }
  }

  getDisplayScore(result: AnalysisResult | null): number | null {
    if (!result) return null;
    
    // Calculate custom score
    const lScore = result.trustScore ?? 0;
    const sScore = this.getSellerScore(result) ?? 0;
    const pScore = this.getPriceScore(result) ?? 0;
    
    const wL = this.customListingWeight;
    const wS = this.customSellerWeight;
    const wP = this.customPriceWeight;
    
    const totalWeight = wL + wS + wP;
    if (totalWeight === 0) return 0;
    
    const customScore = (lScore * wL + sScore * wS + pScore * wP) / totalWeight;
    return customScore;
  }

  getSellerScore(result: AnalysisResult | null): number | null {
    return this.service.getSellerScore(result);
  }

  getPriceScore(result: AnalysisResult | null): number | null {
    return this.service.getPriceScore(result);
  }

  getPriceSignalLabel(result: AnalysisResult | null): string {
    return this.service.getPriceSignalLabel(result);
  }

  getTrustColor(score: number | null, isSuspicious?: boolean): string {
    return this.service.getTrustColorClass(score, isSuspicious);
  }

  getOverallScoreLabel(result: AnalysisResult | null): string {
    return this.service.getOverallScoreLabel(result);
  }

  getRiskLabel(risk: string): string {
    return this.service.getRiskLabel(risk);
  }

  getRiskExplanation(risk: string): string {
    return this.service.getRiskExplanation(risk);
  }

  formatName(name?: string): string {
    if (!name) return '';
    return name.split(' ')
      .map(word => {
        if (!word) return '';
        const lower = word.toLowerCase();
        if (lower === 'iphone') return 'iPhone';
        if (lower.endsWith('gb')) return lower.toUpperCase(); // "256gb" -> "256GB"
        return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
      })
      .join(' ');
  }

  formatAge(months?: number): string {
    if (!months) return '0m';
    if (months < 12) return `${months}m`;
    const yrs = months / 12;
    if (yrs % 1 === 0) return `${yrs} god`;
    return `${yrs.toFixed(1)} god`;
  }

  getPriceDiff(market: number, listing?: number): number | null {
    if (!listing || !market) return null;
    return Math.round(((listing - market) / market) * 100);
  }

  getRecTypeIcon(type: string): string {
    switch (type) {
      case 'price_peer': return 'swap_horiz';
      case 'value_upgrade': return 'trending_up';
      case 'budget_saver': return 'savings';
      default: return 'recommend';
    }
  }

  getAdviceMessages(res: AnalysisResult | null): string[] {
    if (!res) return [];
    const messages: string[] = [];

    // Anomaly checks (ML or LLM signals)
    const isPriceAnomaly = res.isAnomaly || (res.uiAlerts && (res.uiAlerts.includes('Visoka cijena') || res.uiAlerts.includes('Sumnjiva cijena') || res.uiAlerts.includes('Nerealna cijena')));
    
    if (isPriceAnomaly) {
      const type = (res.anomalyType || '').toLowerCase();
      const alerts = (res.uiAlerts || []).map(a => a.toLowerCase());
      
      if (type.includes('too_good') || type.includes('suspiciously_low') || alerts.includes('sumnjiva cijena') || alerts.includes('nerealna cijena')) {
        messages.push('Ovaj artikal ima sumnjivu cijenu, preporučujemo da budete više nego oprezni s njim! Ne savjetujemo kupovinu bez osobnog pregleda.');
        messages.push('Ovaj oglas je previše dobar da bi bio istinit.');
      } else if (type.includes('overpriced') || type.includes('too_high') || alerts.includes('visoka cijena')) {
        messages.push('Ovaj artikal ima previše visoku cijenu, nastavite gledati dalje na stranici.');
      } else {
        messages.push('Ovaj artikal ima sumnjivu cijenu, preporučujemo da budete više nego oprezni s njim! Ne savjetujemo kupovinu bez osobnog pregleda.');
      }
    }

    // Seller checks
    if (res.sellerTrust !== null && res.sellerTrust < 0.5) {
      messages.push('Ovaj prodavač nije baš pouzdan, najbolje bi bilo da potražite drugog.');
    }
    if (res.isNewSeller) {
      messages.push('Ovaj prodavač je tek nedavno došao na platformu, savjetujemo oprez!');
    }

    // Low trust score check
    const score = this.getDisplayScore(res);
    if (score !== null && score < 5) {
      let issues = '';
      if (res.risks && res.risks.length > 0) {
        issues = ' Glavni problemi: ' + res.risks.map(r => this.getRiskLabel(r)).join(', ') + '.';
      }
      messages.push('Ovaj oglas ima nizak indeks povjerenja.' + issues);
    }

    return messages;
  }


  getRecTypeColor(type: string): string {
    switch (type) {
      case 'price_peer': return '#42a5f5';
      case 'value_upgrade': return '#66bb6a';
      case 'budget_saver': return '#ffa726';
      default: return '#90a4ae';
    }
  }

  openListing(itemId: string): void {
    // Defensively strip any leading slashes that might exist in DB
    const cleanId = itemId?.toString().replace(/^\/+/, '') ?? '';
    const url = `https://www.olx.ba/artikal/${cleanId}`;
    chrome?.tabs?.create({ url }) ?? window.open(url, '_blank');
  }

  toggleScoreBreakdown(): void {
    this.scoreBreakdownOpen.update((value) => !value);
  }
}
