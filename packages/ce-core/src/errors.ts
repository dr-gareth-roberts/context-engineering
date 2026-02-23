export class ContextEngineeringError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "ContextEngineeringError";
    this.code = code;
  }
}

export class ValidationError extends ContextEngineeringError {
  readonly details: Array<{ path: string; message: string }>;

  constructor(
    message: string,
    details: Array<{ path: string; message: string }> = []
  ) {
    super(message, "VALIDATION_ERROR");
    this.name = "ValidationError";
    this.details = details;
  }
}

export class BudgetExceededError extends ContextEngineeringError {
  constructor(message: string) {
    super(message, "BUDGET_EXCEEDED");
    this.name = "BudgetExceededError";
  }
}

export class EstimationError extends ContextEngineeringError {
  constructor(message: string) {
    super(message, "ESTIMATION_ERROR");
    this.name = "EstimationError";
  }
}
