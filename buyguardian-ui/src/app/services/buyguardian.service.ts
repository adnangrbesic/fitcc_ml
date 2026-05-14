import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError, of } from 'rxjs';
import { catchError, timeout } from 'rxjs/operators';
import * as signalR from '@microsoft/signalr';

export interface AnalysisResult {
  trustScore: number;
  overallScore?: number;
  isNewSeller?: boolean;
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
  // Expanded stats
  positiveFeedback?: number;
  negativeFeedback?: number;
  successfulDeliveries?: number;
  accountAgeMonths?: number;
  cheapestItemId?: string;
  cheapestPrice?: number;
  cheapestTitle?: string;
  cheapestSellerName?: string;
  uiAlerts?: string[];
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
  low_trust: 'Nizak nivo povjerenja',
  new_listing: 'Novi oglas',
  new_account: 'Novi korisnički profil',
  high_volatility: 'Nestabilna cijena',
  empty_description: 'Nedostaje opis artikla',
  low_feedback: 'Malo feedbacka',
  price_too_low: 'Sumnjivo niska cijena',
  no_phone: 'Nema telefona',
  no_email: 'Email nije verifikovan',
  high_price: 'Cijena iznad prosjeka',
};

const RISK_EXPLANATIONS: Record<string, string> = {
  low_trust: 'Ukupna analiza ukazuje na pojačane rizike kupovine kod ovog artikla.',
  new_listing: 'Oglas je postavljen nedavno i nemamo historiju kretanja cijene za praćenje manipulacije.',
  new_account: 'Profil prodavača je svjež (manje od 3 mjeseca starosti), budite oprezni.',
  high_volatility: 'Cijena ovog proizvoda često varira u kratkom vremenu.',
  empty_description: 'Oglas nema tekstualni opis što je čest pokazatelj lažnih oglasa ili spama.',
  underpriced: 'Cijena je statistički znatno niža od tržišnog prosjeka za ovaj model.',
  overpriced: 'Proizvod se prodaje po cijeni znatno većoj od trenutnog tržišnog vrha.',
  price_anomaly: 'Mašinsko učenje je detektovalo nepravilnost u korelaciji cijene i ostatka ponude.',
  suspicious_profile: 'Analiza profila ukazuje na anomalije u aktivnostima ili verifikaciji.',
  unverified_seller: 'Korisnik nije prošao validaciju broja telefona ili emaila.',
  condition_price_mismatch: 'Prijavljeno stanje proizvoda ne odgovara cijeni po kojoj se prodaje.',
  too_good_to_be_true: 'Sve statistike ovog oglasa su na granici realnog, preporučujemo dodatnu provjeru.',
  suspicious_description: 'Uzorak pisanja u opisu podsjeća na generisani spam ili lažne informacije.',
  price_deviation: 'Veliko statističko odstupanje od medijana grupacije.',
  condition_to_price: 'Skener stanja i cijene detektuje nelogičnost.',
  warranty_weight: 'Vremenski okvir garancije izgleda nelogično ili izmišljeno.',
  seller_reliability: 'Učestalost transakcija ili statistike upućuju na slab rejting prodavača.',
  negative_feedback_ratio: 'Visok procenat negativnih dojmova u odnosu na ukupan broj prodaja.',
  spam_score: 'Visoka vjerovatnoća da je oglas kreiran botom ili skriptom.',
  listing_staleness: 'Oglas predugo stoji bez izmjena dok tržište diktira druge uslove.',
  price_volatility: 'Izražene varijacije cijene unutar samog artikla u bazi podataka.',
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
            if (err.status === 404) {
              // Not found (processing), connect to SignalR
              this.waitForSignalR(baseUrl, itemId, resolve, reject);
              return of(null as any); // prevent further error propagation
            }
            const parsedErr = this.parseError(err);
            reject(parsedErr);
            return throwError(() => parsedErr);
          })
        ).subscribe(result => {
          if (result) resolve(result); // result is null if we went down the SignalR path
        });
    });
  }

  private async waitForSignalR(baseUrl: string, itemId: string, resolve: Function, reject: Function) {
    const connection = new signalR.HubConnectionBuilder()
      .withUrl(`${baseUrl}/hubs/analysis`)
      .withAutomaticReconnect()
      .build();

    connection.on('AnalysisComplete', async (id: string) => {
      if (id === itemId) {
        // Stop connection as we got our result
        await connection.stop();
        // Retry the HTTP request now that it's ready
        this.http.post<AnalysisResult>(`${baseUrl}/api/analyze/${itemId}`, {})
          .subscribe({
             next: res => resolve(res),
             error: err => reject(this.parseError(err))
          });
      }
    });

    try {
      await connection.start();
      // Join the group
      await connection.invoke('JoinGroup', itemId);
      
      // Set a timeout just in case it hangs forever
      setTimeout(async () => {
        if (connection.state === signalR.HubConnectionState.Connected) {
          await connection.stop();
          reject({ message: 'Procesiranje traje predugo. Pokušajte ponovo kasnije.', offline: false });
        }
      }, 60000); // 1 minute timeout for ML scraping
    } catch (err) {
      console.error("SignalR connection error: ", err);
      reject({ message: 'Nije moguće uspostaviti real-time konekciju sa serverom.', offline: false });
    }
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
    // Defensive cleanup of accidental stacked prefixes: "anomaly_anomaly_something" -> "something"
    if (risk.includes('anomaly_')) {
      const type = risk.replace(/anomaly_/g, '').trim();
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

  getRiskExplanation(risk: string): string {
    if (risk.includes('anomaly_')) {
      const type = risk.replace(/anomaly_/g, '').trim();
      return RISK_EXPLANATIONS[type] ?? 'ML model je detektovao odstupanje od standardnih obrazaca trgovine.';
    }
    return RISK_EXPLANATIONS[risk] ?? 'Dodatni faktor rizika uočen tokom automatske inspekcije oglasa.';
  }

}
