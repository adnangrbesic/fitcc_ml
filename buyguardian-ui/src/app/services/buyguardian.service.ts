import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError, of } from 'rxjs';
import { catchError, timeout } from 'rxjs/operators';

export interface AnalysisResult {
  trustScore: number;
  marketPrice: number;
  listingPrice?: number;
  risks: string[];
  sellerTrust: number;
  sellerFeedback?: number;
  condition?: number;
  warrantyMonths?: number;
  category?: string;
  productName?: string;
  // Anomaly fields
  anomalyScore?: number;
  isAnomaly?: boolean;
  anomalyType?: string;
}

export interface Recommendation {
  itemId: string;
  title: string;
  price: number;
  sellerTrust: number;
  sellerName: string;
  productName: string;
  type: 'price_peer' | 'value_upgrade' | 'budget_saver';
  badge: string;
  reason: string;
}

export interface AnalysisError {
  message: string;
  offline: boolean;
}

const RISK_LABELS: Record<string, string> = {
  low_feedback: 'Malo feedbacka',
  price_too_low: 'Sumnjivo niska cijena',
  new_account: 'Novi nalog',
  new_listing: 'Novi oglas',
  no_phone: 'Nema telefona',
  no_email: 'Email nije verifikovan',
  high_price: 'Cijena iznad prosjeka',
  low_trust: 'Nizak seller trust',
  empty_description: 'Prazan opis oglasa',
};

@Injectable({ providedIn: 'root' })
export class BuyGuardianService {
  private http = inject(HttpClient);
  // IP adresa VM servera iz grafa
  private defaultUrl = 'http://localhost:5000';

  private getBaseUrl(): Promise<string> {
    return new Promise((resolve) => {
      if (!chrome?.storage?.local) return resolve(this.defaultUrl);
      chrome.storage.local.get('api_base_url', (res: Record<string, any>) => {
        resolve(res['api_base_url'] || this.defaultUrl);
      });
    });
  }

  async analyze(itemId: string): Promise<AnalysisResult> {
    const baseUrl = await this.getBaseUrl();
    return new Promise((resolve, reject) => {
      this.http.post<AnalysisResult>(`${baseUrl}/api/analyze/${itemId}`, {})
        .pipe(
          timeout(15000),
          catchError((err: HttpErrorResponse) => {
            const parsedErr = this.parseError(err);
            reject(parsedErr);
            return throwError(() => parsedErr);
          })
        ).subscribe(resolve);
    });
  }

  async getRecommendations(itemId: string): Promise<Recommendation[]> {
    const baseUrl = await this.getBaseUrl();
    return new Promise((resolve) => {
      this.http.get<Recommendation[]>(`${baseUrl}/api/listings/${itemId}/recommendations`)
        .pipe(
          timeout(10000),
          catchError(() => of([]))
        ).subscribe(resolve);
    });
  }

  saveConfig(url: string): Promise<void> {
    return new Promise((resolve) => {
      if (chrome?.storage?.local) {
        chrome.storage.local.set({ 'api_base_url': url }, () => resolve());
      } else {
        resolve();
      }
    });
  }

  getConfig(): Promise<string> {
    return this.getBaseUrl();
  }

  private parseError(error: HttpErrorResponse): AnalysisError {
    if (error.status === 0) {
      return { message: 'Backend nedostupan. Provjeri da li API radi.', offline: true };
    }
    if (error.status === 404) {
      return { message: 'Oglas se trenutno obrađuje. Sačekaj par sekundi pa probaj ponovo...', offline: false };
    }
    return { message: error.error?.message || 'Došlo je do greške prilikom analize.', offline: false };
  }

  /**
   * Try to load cached analysis from chrome.storage.local.
   * Returns null if no valid cache exists.
   */
  getCachedAnalysis(itemId: string): Promise<AnalysisResult | null> {
    if (!chrome?.storage?.local) return Promise.resolve(null);

    return new Promise((resolve) => {
      const cacheKey = `analysis_${itemId}`;
      chrome.storage.local.get(cacheKey, (result: Record<string, any>) => {
        const cached = result[cacheKey];
        if (cached?.data) {
          const ageMinutes = (Date.now() - cached.timestamp) / 60000;
          if (ageMinutes < 60) {
            resolve(cached.data as AnalysisResult);
            return;
          }
        }
        resolve(null);
      });
    });
  }

  /**
   * Try to load cached recommendations from chrome.storage.local.
   */
  getCachedRecommendations(itemId: string): Promise<Recommendation[] | null> {
    if (!chrome?.storage?.local) return Promise.resolve(null);

    return new Promise((resolve) => {
      const recKey = `recs_${itemId}`;
      chrome.storage.local.get(recKey, (result: Record<string, any>) => {
        const cached = result[recKey];
        if (cached?.data) {
          const ageMinutes = (Date.now() - cached.timestamp) / 60000;
          if (ageMinutes < 60) {
            resolve(cached.data as Recommendation[]);
            return;
          }
        }
        resolve(null);
      });
    });
  }

  getRiskLabel(risk: string): string {
    // Handle anomaly_ prefixed risks
    if (risk.startsWith('anomaly_')) {
      const type = risk.replace('anomaly_', '');
      const anomalyLabels: Record<string, string> = {
        underpriced: 'Sumnjivo niska cijena (ML)',
        overpriced: 'Previsoka cijena (ML)',
        price_anomaly: 'Anomalija u cijeni (ML)',
        suspicious_profile: 'Sumnjiv profil',
        unverified_seller: 'Neprovjereni prodavač',
        condition_price_mismatch: 'Stanje/cijena ne odgovaraju',
        too_good_to_be_true: 'Prelijepo da bi bilo istinito',
        suspicious_description: 'Sumnjiv opis',
        price_deviation: 'Veliko odstupanje cijene',
        condition_to_price: 'Cijena ne odgovara stanju',
        warranty_weight: 'Sumnjiva garancija',
        seller_reliability: 'Nepouzdan prodavač',
        negative_feedback_ratio: 'Negativni dojmovi',
        spam_score: 'Potencijalni spam',
        listing_staleness: 'Zastario oglas',
        price_volatility: 'Nestabilna cijena',
      };
      return anomalyLabels[type] ?? `Anomalija: ${type.replace(/_/g, ' ')}`;
    }
    return RISK_LABELS[risk] ?? risk.replace(/_/g, ' ');
  }

}
