# RiskWise 2.0 — Production Deployment & Infrastructure Guide

## 1. Production Architecture Overview

RiskWise 2.0 is designed for high-availability, mission-critical enterprise deployment on Amazon Web Services (AWS) using containerized microservices managed by AWS ECS Fargate, backed by Amazon Aurora / RDS PostgreSQL Multi-AZ and Amazon ElastiCache Valkey/Redis.

```mermaid
flowchart TD
    CF[Amazon CloudFront CDN / WAF]
    ALB[Application Load Balancer]
    
    subgraph VPC["Multi-AZ Virtual Private Cloud (VPC)"]
        subgraph PublicSubnets["Public Subnets"]
            NAT[NAT Gateways]
        end
        
        subgraph PrivateApp["Private App Subnets"]
            ECS_WEB[ECS Fargate Tasks: Next.js Frontend\n(Min 2, Max 10)]
            ECS_API[ECS Fargate Tasks: FastAPI Backend\n(Min 2, Max 20)]
        end
        
        subgraph PrivateData["Private Isolated Data Subnets"]
            RDS_PRI[(Amazon RDS PostgreSQL 16\nMulti-AZ Primary)]
            RDS_STDBY[(RDS Standby Replica)]
            VALKEY[(ElastiCache Valkey / Redis Cluster\nMulti-AZ Auto-Failover)]
            KMS[AWS KMS Customer Managed Keys]
        end
    end
    
    USERS[Enterprise Operators & Clients] --> CF
    CF --> ALB
    ALB --> ECS_WEB
    ALB --> ECS_API
    ECS_WEB --> ECS_API
    ECS_API --> RDS_PRI
    RDS_PRI -.-> RDS_STDBY
    ECS_API --> VALKEY
    ECS_API --> KMS
    ECS_API -.->|Telemetry Feeds| NAT
```

---

## 2. Infrastructure as Code (Terraform)

All infrastructure is declaratively defined in `infra/terraform/`:

- `main.tf`: Defines VPC, public/private subnets across 3 Availability Zones, Security Groups, IAM Roles (least-privilege with OIDC trust), ECS Cluster, Fargate Task Definitions, Service Auto-Scaling Policies, RDS Multi-AZ PostgreSQL 16 instance, ElastiCache Redis replication group, Application Load Balancer, and CloudFront distribution.
- `variables.tf`: Configurable parameters (`aws_region`, `environment`, `project_name`, `vpc_cidr`, `db_instance_class`, `container_cpu`, `container_memory`).
- `outputs.tf`: Exports ALB DNS name, CloudFront distribution domain, RDS endpoint, and ECR repository URIs.

### Provisioning Infrastructure

```bash
cd infra/terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

---

## 3. Container Specifications

### 3.1 Backend Container (`api/Dockerfile`)
- **Base Image**: `python:3.13-slim`
- **Security**: Runs as non-root user `riskwise` (UID 10001).
- **Optimization**: Multi-stage build eliminating build-essential compilers from final runtime image.
- **Port**: 8000
- **Healthcheck**:
  ```dockerfile
  HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
      CMD curl -f http://localhost:8000/health || exit 1
  ```

### 3.2 Frontend Container (`web/Dockerfile`)
- **Base Image**: `node:24-alpine`
- **Output**: Next.js Standalone build (`output: 'standalone'` in `next.config.ts`), minimizing image size to ~120MB.
- **Security**: Non-root user `nextjs` (UID 1001).
- **Port**: 3000

---

## 4. CI/CD Deployment Automation

The repository includes a battle-tested GitHub Actions workflow at `.github/workflows/production.yml` triggered on push to `main`:

1. **Stage 1: Backend Verification**: Executes 4,500+ pytest tests with strict zero-failure assertion.
2. **Stage 2: Frontend Verification**: Executes `npm ci`, `npx tsc --noEmit`, `eslint`, `npm test`, and `npm run build`.
3. **Stage 3: Security & Secret Scan**: Audits npm packages and scans git tree for accidental credentials (`AKIA...`, private keys).
4. **Stage 4: Evaluation Suite**: Runs 16 automated agent evaluation suites against golden disruption scenarios.
5. **Stage 5: Container Build & Push**: Uses GitHub OIDC (`sts:AssumeRoleWithWebIdentity`) to authenticate directly to AWS ECR without static access keys.
6. **Stage 6: Zero-Downtime Deployment**: Updates ECS service with new task definition and initiates rolling update.

---

## 5. Production Operations & Rollback

### Zero-Downtime Rolling Update Policy
- **Minimum Healthy Percent**: 100% (ensures existing capacity is preserved throughout deployment)
- **Maximum Percent**: 200% (provisions new containers alongside existing before routing traffic)
- **Circuit Breaker**: `enable_circuit_breaker = true` automatically rolls back the ECS service to the previous stable task definition if healthchecks fail within 3 minutes.

### Operational Runbook: Manual Rollback
If a defect bypasses staging:
```bash
aws ecs update-service \
    --cluster riskwise-production \
    --service riskwise-api \
    --task-definition riskwise-api:<PREVIOUS_STABLE_REVISION> \
    --force-new-deployment
```
