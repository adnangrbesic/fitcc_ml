import { Component, OnInit, signal, inject, effect, AfterViewInit, ElementRef, ViewChild } from '@angular/core';
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

import { BuyGuardianService, AnalysisResult, AnalysisError, Recommendation, VoteResponse, VoteStatusResponse, PriceAlertResponse, PriceAlertStatusResponse, TriggeredAlertInfo } from './services/buyguardian.service';

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
export class App implements OnInit, AfterViewInit {
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

  // Voting state
  userVote = signal<'up' | 'down' | null>(null);
  voteSubmitting = signal(false);
  voteMessage = signal('');
  communityScore = signal<number | null>(null);
  voteTotal = signal(0);
  viewedAt: Date = new Date();

  // Price alert state
  alertSubscribed = signal(false);
  alertSubmitting = signal(false);
  alertMessage = signal('');

  // Side-by-side comparison
  compareModeActive = signal(false);      // Selection mode: checkboxes visible
  comparedRecs = signal<Set<string>>(new Set());
  showFullComparison = signal(false);     // Fullscreen comparison overlay

  readonly listingWeight = 0.7;
  readonly sellerWeight = 0.3;
  readonly pricePenaltyMax = 2.0;

  customListingWeight = 40;
  customSellerWeight = 30;
  customPriceWeight = 30;

  animatedScore = signal<number>(0);
  animatedRingOffset = signal<number>(251.33); // 2 * Math.PI * 40
  showCopiedToast = signal(false);
  showConfetti = signal(false);
  private animationFrameId: number | null = null;
  private confettiObserver: IntersectionObserver | null = null;
  @ViewChild('confettiAnchor') confettiAnchor!: ElementRef;

  constructor() {
    effect(() => {
      const res = this.result();
      const score = this.getDisplayScore(res);
      if (score !== null && score !== undefined) {
        this.animateScore(score);
      } else {
        this.animatedScore.set(0);
        this.animatedRingOffset.set(251.33);
      }
    });
  }

  async ngOnInit(): Promise<void> {
    this.settingsApiUrl.set(await this.service.getConfig());
    const weights = await this.service.getWeights();
    this.customListingWeight = weights.listing;
    this.customSellerWeight = weights.seller;
    this.customPriceWeight = weights.price;

    // Reset viewedAt for time-gated voting
    this.viewedAt = new Date();

    this.detectFromCurrentTab();

    // Poll for pending price alerts every 5 minutes
    setInterval(() => this.checkPendingAlerts(), 5 * 60 * 1000);
    this.checkPendingAlerts();
  }

  ngAfterViewInit(): void {
    // Lazy confetti: only start when user scrolls to the "Čestitamo!" section
    this.confettiObserver = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          this.showConfetti.set(true);
          this.confettiObserver?.disconnect();
        }
      },
      { threshold: 0.3 }
    );
    // Observe after a short delay to let DOM render
    setTimeout(() => {
      if (this.confettiAnchor) {
        this.confettiObserver?.observe(this.confettiAnchor.nativeElement);
      }
    }, 500);
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
        this.loadVoteStatus();
        this.loadAlertStatus();
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
      this.loadVoteStatus();
      this.loadAlertStatus();
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

  getBulletOffset(market: number, listing: number): number {
    if (!market || !listing) return 50;
    const ratio = listing / market;
    let offset = (ratio - 0.5) * 100;
    return Math.max(5, Math.min(95, offset));
  }

  getBulletWidth(offset: number): number {
    return Math.abs(offset - 50);
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
    if (!months) return '0 mj.';
    if (months < 12) return `${months} mj.`;
    const yrs = months / 12;
    if (yrs % 1 === 0) return `${yrs} god.`;
    return `${yrs.toFixed(1)} god.`;
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

  private animateScore(targetScore: number): void {
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
    }
    const duration = 800;
    const startTime = performance.now();
    const startScore = this.animatedScore();
    const circumference = 2 * Math.PI * 40;

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const ease = 1 - Math.pow(1 - progress, 3);
      const currentScore = startScore + (targetScore - startScore) * ease;
      this.animatedScore.set(currentScore);
      
      const targetOffset = circumference - (currentScore / 10) * circumference;
      this.animatedRingOffset.set(targetOffset);

      if (progress < 1) {
        this.animationFrameId = requestAnimationFrame(animate);
      } else {
        this.animatedScore.set(targetScore);
        this.animatedRingOffset.set(circumference - (targetScore / 10) * circumference);
        this.animationFrameId = null;
      }
    };
    this.animationFrameId = requestAnimationFrame(animate);
  }

  getQuickSummary(res: AnalysisResult): { text: string; icon: string; type: 'positive' | 'warning' | 'danger' } {
    if (res.isSuspicious) {
      return {
        text: 'Sistem je detektovao ozbiljne rizike. Preporučujemo maksimalan oprez!',
        icon: 'gpp_bad',
        type: 'danger'
      };
    }

    const score = this.getDisplayScore(res) ?? 0;
    const isNew = res.isNewSeller === true;
    const isAnomaly = res.isAnomaly === true;

    // Price comparison logic
    let priceDiff: number | null = null;
    if (res.marketPrice && res.listingPrice) {
      priceDiff = Math.round(((res.listingPrice - res.marketPrice) / res.marketPrice) * 100);
    }

    if (score >= 7) {
      if (priceDiff !== null && priceDiff < 0) {
        return {
          text: `Oglas izgleda pouzdano. Cijena je ${Math.abs(priceDiff)}% ispod tržišnog prosjeka.`,
          icon: 'check_circle',
          type: 'positive'
        };
      }
      return {
        text: 'Oglas izgleda pouzdano.',
        icon: 'check_circle',
        type: 'positive'
      };
    } else if (score >= 5) {
      if (isNew) {
        return {
          text: 'Prodavač je nov na platformi. Preporučujemo dodatni oprez.',
          icon: 'warning',
          type: 'warning'
        };
      }
      return {
        text: 'Oglas je prosječan. Provjerite detalje prije kupovine.',
        icon: 'info',
        type: 'warning'
      };
    } else {
      if (isAnomaly) {
        return {
          text: 'Upozorenje: Cijena je sumnjivo niska za ovaj model, a prodavač nema historiju.',
          icon: 'error',
          type: 'danger'
        };
      }
      return {
        text: 'Oprez: Ovaj oglas ima nizak indeks povjerenja.',
        icon: 'error',
        type: 'danger'
      };
    }
  }

  shareAnalysis(res: AnalysisResult): void {
    const score = this.getDisplayScore(res);
    const label = this.getOverallScoreLabel(res);
    const price = res.listingPrice || 0;
    const diff = res.marketPrice ? Math.round(((price - res.marketPrice) / res.marketPrice) * 100) : 0;
    const sellerTrust = Math.round(res.sellerTrust * 100);
    const itemId = this.itemId();

    const text = `🛡️ BuyGuardian analiza: ${this.formatName(res.productName || 'Artikal')}
Ocjena: ${score !== null ? score.toFixed(1) : '—'}/10 — ${label}
Cijena: ${price} KM (${diff > 0 ? '+' : ''}${diff}% od prosjeka)
Prodavač: ${sellerTrust}% pozitivni
Link: https://olx.ba/artikal/${itemId}`;

    navigator.clipboard.writeText(text).then(() => {
      this.showCopiedToast.set(true);
      setTimeout(() => {
        this.showCopiedToast.set(false);
      }, 2000);
    }).catch(err => {
      console.error('Failed to copy text: ', err);
    });
  }

  // ── Voting (#10) ─────────────────────────────────────────────────────

  async loadVoteStatus(): Promise<void> {
    const id = this.itemId();
    if (!id) return;
    const fp = this.service.getFingerprint();
    const status = await this.service.getVoteStatus(id, fp);
    this.communityScore.set(status.aggregateScore ?? null);
    this.voteTotal.set(status.totalVotes);
    if (status.yourVote === 'up' || status.yourVote === 'down') {
      this.userVote.set(status.yourVote);
    }
  }

  async castVote(vote: 'up' | 'down'): Promise<void> {
    if (this.voteSubmitting()) return;
    const id = this.itemId();
    if (!id) return;

    this.voteSubmitting.set(true);
    this.voteMessage.set('');

    const fp = this.service.getFingerprint();
    const response = await this.service.castVote(id, vote, fp, this.viewedAt);

    if (response.accepted) {
      this.userVote.set(vote);
      this.communityScore.set(response.aggregateScore ?? null);
    }
    this.voteMessage.set(response.reason);
    this.voteSubmitting.set(false);

    // Clear message after 3 seconds
    setTimeout(() => this.voteMessage.set(''), 3000);
  }

  // ── Price Alert (#9) ─────────────────────────────────────────────────

  async loadAlertStatus(): Promise<void> {
    const id = this.itemId();
    if (!id) return;
    const fp = this.service.getFingerprint();
    const status = await this.service.getAlertStatus(id, fp);
    this.alertSubscribed.set(status.isSubscribed);
  }

  async togglePriceAlert(): Promise<void> {
    if (this.alertSubmitting()) return;
    const id = this.itemId();
    if (!id) return;

    this.alertSubmitting.set(true);
    const fp = this.service.getFingerprint();

    if (this.alertSubscribed()) {
      await this.service.unsubscribePriceAlert(id, fp);
      this.alertSubscribed.set(false);
      this.alertMessage.set('Obavijest isključena.');
    } else {
      const res = await this.service.subscribePriceAlert(id, fp);
      if (res.alertId) {
        this.alertSubscribed.set(true);
      }
      this.alertMessage.set(res.message);
    }

    this.alertSubmitting.set(false);
    setTimeout(() => this.alertMessage.set(''), 4000);
  }

  async checkPendingAlerts(): Promise<void> {
    const fp = this.service.getFingerprint();
    try {
      const alerts = await this.service.getPendingAlerts(fp);
      for (const alert of alerts) {
        // Show Chrome notification if available
        if (chrome?.notifications) {
          chrome.notifications.create(`price-alert-${alert.itemId}`, {
            type: 'basic',
            iconUrl: 'icons/icon128.png',
            title: '📉 Cijena pala!',
            message: `${alert.title}: ${alert.oldPrice} → ${alert.newPrice} KM (ušteda ${alert.savingsPercent}%)`,
            priority: 2
          });
        }
      }
    } catch { /* silent */ }
  }

  // ── Side-by-side Comparison (#11) ────────────────────────────────────

  toggleCompareMode(): void {
    this.compareModeActive.update(v => !v);
    if (!this.compareModeActive()) {
      this.comparedRecs.set(new Set());
    }
  }

  toggleCompareRec(itemId: string): void {
    if (!this.compareModeActive()) return;
    const set = new Set(this.comparedRecs());
    if (set.has(itemId)) {
      set.delete(itemId);
    } else {
      if (set.size >= 2) {
        const first = set.values().next().value;
        if (first) set.delete(first);
      }
      set.add(itemId);
    }
    this.comparedRecs.set(set);
  }

  isCompared(itemId: string): boolean {
    return this.comparedRecs().has(itemId);
  }

  openFullComparison(): void {
    if (this.comparedRecs().size === 0) return;
    this.showFullComparison.set(true);
  }

  closeFullComparison(): void {
    this.showFullComparison.set(false);
  }

  getComparedRecommendations(): Recommendation[] {
    const selectedIds = this.comparedRecs();
    return this.recommendations().filter(r => selectedIds.has(r.itemId));
  }

  // ── Dynamic comparison helpers ────────────────────────────────────

  /// Returns attribute keys that all compared items have in common (plus current listing)
  getCommonAttributeKeys(): string[] {
    const current = this.result()?.attributes;
    const recs = this.getComparedRecommendations();

    // Collect all attribute keys from current listing
    const currentKeys = new Set(current ? Object.keys(current) : []);

    // Find keys present in ALL recommendations too
    const common: string[] = [];
    for (const key of currentKeys) {
      if (recs.every(r => r.attributes && key in r.attributes)) {
        common.push(key);
      }
    }
    return common;
  }

  /// Format an attribute value for display
  formatAttrValue(value: any): string {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'number') {
      if (Number.isInteger(value)) return value.toString();
      return value.toFixed(1);
    }
    if (typeof value === 'object') {
      const inner = value.value ?? value.Value ?? '';
      return String(inner !== '[object Object]' ? inner : '—');
    }
    return String(value);
  }

  /// Check if a value is numeric (for display as dynamic attr row)
  isNumericAttr(value: any): boolean {
    if (value === null || value === undefined) return false;
    if (typeof value === 'number') return true;
    if (typeof value === 'string') {
      const parsed = parseFloat(value.replace(',', '.'));
      return !isNaN(parsed);
    }
    // Handle objects that might have a numeric representation
    if (typeof value === 'object' && value !== null) {
      const str = String(value.value ?? value.Value ?? value);
      if (str && str !== '[object Object]') {
        const parsed = parseFloat(str.replace(',', '.'));
        return !isNaN(parsed);
      }
    }
    return false;
  }

  /// Try to parse numeric value (handles strings, numbers, and objects)
  parseNumericAttr(value: any): number | null {
    if (value === null || value === undefined) return null;
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      const parsed = parseFloat(value.replace(',', '.'));
      return isNaN(parsed) ? null : parsed;
    }
    if (typeof value === 'object') {
      const str = String(value.value ?? value.Value ?? '');
      if (str && str !== '[object Object]') {
        const parsed = parseFloat(str.replace(',', '.'));
        return isNaN(parsed) ? null : parsed;
      }
    }
    return null;
  }

  /// Simple numeric extraction for comparison — handles strings/numbers/objects
  numVal(value: any): number | null {
    if (value === null || value === undefined) return null;
    if (typeof value === 'number') return value;
    const str = typeof value === 'string' ? value : String(value?.value ?? value?.Value ?? '');
    const n = parseFloat(str.replace(',', '.'));
    return isNaN(n) ? null : n;
  }

  /// For template: is this recommendation STRICTLY better than current for this attr?
  isBetterThanCurrent(rec: Recommendation, attrKey: string, currentVal: any): boolean {
    const rv = this.numVal(rec.attributes?.[attrKey]);
    const cv = this.numVal(currentVal);
    if (rv === null || cv === null || rv === cv) return false;
    const lowerIsBetter = /price|cijena|cost|km|eur/i.test(attrKey);
    return lowerIsBetter ? rv < cv : rv > cv;
  }

  /// For template: is this recommendation the best among ALL compared?
  isBestAmongAll(rec: Recommendation, attrKey: string, all: Recommendation[], currentVal: any): boolean {
    const rv = this.numVal(rec.attributes?.[attrKey]);
    const cv = this.numVal(currentVal);
    if (rv === null || cv === null) return false;
    const lowerIsBetter = /price|cijena|cost|km|eur/i.test(attrKey);

    // Check against current and all other recs
    if (lowerIsBetter) {
      if (rv >= cv) return false;
      for (const other of all) {
        if (other.itemId === rec.itemId) continue;
        const ov = this.numVal(other.attributes?.[attrKey]);
        if (ov !== null && ov <= rv) return false;
      }
      return true;
    } else {
      if (rv <= cv) return false;
      for (const other of all) {
        if (other.itemId === rec.itemId) continue;
        const ov = this.numVal(other.attributes?.[attrKey]);
        if (ov !== null && ov >= rv) return false;
      }
      return true;
    }
  }

  /// Get a display label for an attribute key (human-readable)
  getAttrLabel(key: string): string {
    const labels: Record<string, string> = {
      'ram_gb': 'RAM', 'ram': 'RAM', 'Radna memorija': 'RAM',
      'storage_gb': 'Memorija', 'storage': 'Memorija', 'Interna memorija': 'Memorija',
      'Memorija': 'Memorija', 'Kapacitet': 'Memorija', 'Kapacitet memorije': 'Memorija',
      'battery_health_percent': 'Baterija', 'battery_health': 'Baterija',
      'Zdravlje baterije (%)': 'Baterija', 'Baterija': 'Baterija',
      'condition': 'Stanje', 'stanje': 'Stanje',
      'warranty_months': 'Garancija', 'garancija': 'Garancija',
      'screen_size': 'Ekran', 'screen': 'Ekran', 'Ekran': 'Ekran',
      'processor': 'Procesor', 'cpu': 'Procesor',
      'camera': 'Kamera', 'Kamera': 'Kamera',
      'color': 'Boja', 'boja': 'Boja', 'Boja': 'Boja',
      'year': 'Godina', 'godina': 'Godina', 'Godište': 'Godina',
      'mileage': 'Kilometraža', 'km': 'Kilometraža', 'Kilometraža': 'Kilometraža',
      'engine': 'Motor', 'Motor': 'Motor',
      'fuel': 'Gorivo', 'Gorivo': 'Gorivo',
      'transmission': 'Mjenjač', 'Mjenjač': 'Mjenjač',
    };
    return labels[key] || key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  /// Unique suffix for attr values that are known to have units
  getAttrUnit(key: string): string {
    const units: Record<string, string> = {
      'ram_gb': ' GB', 'ram': ' GB',
      'storage_gb': ' GB', 'storage': ' GB',
      'battery_health_percent': '%', 'screen_size': '"',
      'warranty_months': ' mj.', 'garancija': ' mj.',
      'mileage': ' km', 'km': ' km', 'Kilometraža': ' km',
    };
    return units[key] || '';
  }
}
