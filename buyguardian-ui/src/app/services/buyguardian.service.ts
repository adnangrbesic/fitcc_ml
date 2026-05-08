import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
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
}

export interface AnalysisError {
  message: string;
  offline: boolean;
}

const RISK_LABELS: Record<string, string> = {
  low_feedback: 'Malo feedbacka',
  price_too_low: 'Sumnjivo niska cijena',
  new_account: 'Novi nalog',
  no_phone: 'Nema telefona',
  no_email: 'Email nije verifikovan',
  high_price: 'Cijena iznad prosjeka',
  low_trust: 'Nizak seller trust',
};

@Injectable({ providedIn: 'root' })
export class BuyGuardianService {
  private http = inject(HttpClient);
  // IP adresa VM servera iz grafa
  private baseUrl = 'http://192.168.1.8:5000';

  analyze(itemId: string): Observable<AnalysisResult> {
    return this.http
      .post<AnalysisResult>(`${this.baseUrl}/api/analyze/${itemId}`, {})
      .pipe(
        timeout(15000),
        catchError((err: HttpErrorResponse) => this.handleError(err))
      );
  }

  getRiskLabel(risk: string): string {
    return RISK_LABELS[risk] ?? risk.replace(/_/g, ' ');
  }

  private handleError(err: HttpErrorResponse): Observable<never> {
    const offline = err.status === 0;
    let message = `Greška: ${err.status} ${err.statusText}`;
    
    if (offline) {
      message = 'Backend nedostupan. Provjeri da li API radi.';
    } else if (err.status === 404) {
      message = 'Oglas se trenutno obrađuje. Sačekaj par sekundi pa probaj ponovo...';
    }

    return throwError(() => ({
      message,
      offline,
    }));
  }
}
