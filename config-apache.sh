#!/bin/bash
#
# this script configures certbot and the apache server for a single domain:
#   ${HOSTNAME}.${BASE_DOMAIN}   e.g. node1.devnet.telcoin.network
#
# BASE_DOMAIN and LETSENCRYPT_EMAIL are passed as exported env by the caller
# (genesis.sh / dns.sh). They default to the devnet values if unset, so the
# script is safe to run standalone.

# retrieve hostname (set in startup.sh)
source /etc/environment

# defaults if the caller didn't export them
BASE_DOMAIN="${BASE_DOMAIN:-devnet.telcoin.network}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-devs@telcoin.org}"

NODE_DOMAIN="${HOSTNAME}.${BASE_DOMAIN}"

echo "Hostname from source: ${HOSTNAME}"
echo "Issuing letsencrypt certificate using certbot for: ${NODE_DOMAIN}"

# install certbot
sudo apt install certbot python3-certbot-apache -y

# First, add ServerName to the default HTTP config if it doesn't exist
if ! grep -q "ServerName" /etc/apache2/sites-available/000-default.conf; then
    sudo sed -i "/<VirtualHost \*:80>/a \\    ServerName ${NODE_DOMAIN}" /etc/apache2/sites-available/000-default.conf
fi

# Create default SSL config if it doesn't exist
if [ ! -f "/etc/apache2/sites-available/000-default-le-ssl.conf" ]; then
    sudo cp /etc/apache2/sites-available/000-default.conf /etc/apache2/sites-available/000-default-le-ssl.conf
    sudo sed -i 's/<VirtualHost \*:80>/<VirtualHost *:443>/' /etc/apache2/sites-available/000-default-le-ssl.conf
    sudo sed -i "/<VirtualHost \*:443>/a \\    ServerName ${NODE_DOMAIN}\\n    SSLEngine on" /etc/apache2/sites-available/000-default-le-ssl.conf
else
    # If SSL config exists but doesn't have ServerName, add it
    if ! grep -q "ServerName" /etc/apache2/sites-available/000-default-le-ssl.conf; then
        sudo sed -i "/<VirtualHost \*:443>/a \\    ServerName ${NODE_DOMAIN}" /etc/apache2/sites-available/000-default-le-ssl.conf
    fi
fi

# Enable necessary modules
sudo a2enmod proxy proxy_http ssl rewrite headers setenvif

# Try to obtain certificate for the node domain. This fails until the operator
# points ${NODE_DOMAIN} at this instance's external IP (HTTP-01 challenge); the
# caller treats that as non-fatal and ./dns.sh re-runs this once DNS resolves.
echo "Requesting certificate for ${NODE_DOMAIN}..."
sudo certbot --apache --non-interactive --agree-tos --email "${LETSENCRYPT_EMAIL}" -d "${NODE_DOMAIN}" -v \
    || echo "Failed to get certificate for ${NODE_DOMAIN}"

# Apache Server Setup
# Define variables for file paths
APACHE_CONF_DIR="/etc/apache2"
SSL_CONF="${APACHE_CONF_DIR}/sites-available/000-default-le-ssl.conf"

# Restart Apache to apply module changes
sudo systemctl restart apache2

# Configuration to be inserted
CONFIG_TO_INSERT=$(cat <<'EOF'

    # Custom Proxy and CORS settings

    # Main RPC proxy
    ProxyPreserveHost On
    ProxyPass / http://localhost:8545/
    ProxyPassReverse / http://localhost:8545/

    <IfModule mod_headers.c>
        # make public
        Header always set Access-Control-Allow-Origin "*"
        # RPC is the only publicly exposed server
        Header always set Access-Control-Allow-Methods "POST, GET, OPTIONS"
        Header always set Access-Control-Allow-Headers "X-Requested-With, Content-Type"

        # handle preflight requests - CORS
        SetEnvIf Request_Method "OPTIONS" PREFLIGHT_REQUEST
        RewriteEngine On
        RewriteCond %{ENV:PREFLIGHT_REQUEST} 1
        RewriteRule ^(.*)$ $1 [R=200,L,E=HTTP_ORIGIN:%{HTTP:Origin}]
    </IfModule>

    <IfModule mod_setenvif.c>
        SetEnvIf Request_Method "OPTIONS" PREFLIGHT
    </IfModule>

    <IfModule mod_rewrite.c>
        # preflight for CORS
        RewriteEngine On
        RewriteCond %{ENV:PREFLIGHT} 1
        RewriteRule .* - [R=200,L]
    </IfModule>

EOF
)

# temporary file for content to be inserted
CONTENT_TO_INSERT="temp_apache_config_to_insert.txt"
# temporary output file
TEMP_FILE="default-ssl.conf.temp"

# write to a temporary file
echo "${CONFIG_TO_INSERT}" > "${CONTENT_TO_INSERT}"

# Check if the custom configurations are already in default-ssl.conf to avoid duplication
if grep -q "Custom Proxy and CORS settings" "${SSL_CONF}"; then
    echo "Custom configurations already exist in ${SSL_CONF}"

    # Update the port if needed (from 8544 to 8545)
    if grep -q "http://localhost:8544/" "${SSL_CONF}"; then
        echo "Updating proxy port from 8544 to 8545..."
        sudo sed -i 's|http://localhost:8544/|http://localhost:8545/|g' "${SSL_CONF}"
    fi

    # Remove old healthcheck configurations if they exist
    if grep -q "/healthcheck" "${SSL_CONF}"; then
        echo "Removing old healthcheck proxy configurations..."
        # Remove healthcheck ProxyPass and ProxyPassReverse lines
        sudo sed -i '/ProxyPass \/healthcheck/d' "${SSL_CONF}"
        sudo sed -i '/ProxyPassReverse \/healthcheck/d' "${SSL_CONF}"
        # Remove healthcheck comments
        sudo sed -i '/# Health Check Endpoint/d' "${SSL_CONF}"
        sudo sed -i '/# The healthcheck server responds/d' "${SSL_CONF}"
        sudo sed -i '/# This must come BEFORE/d' "${SSL_CONF}"
        # Remove old healthcheck RewriteRule if it exists
        sudo sed -i '/RewriteRule.*healthcheck.*R=200/d' "${SSL_CONF}"
    fi
else
    # use awk to process and insert content
    awk -v insert_file="${CONTENT_TO_INSERT}" '
    # Before printing the </VirtualHost> line, insert the content of insert_file
    /<\/VirtualHost>/ {
        while ((getline line < insert_file) > 0) {
            print line
        }
        close(insert_file)
    }
    # Print the current line
    { print }
    ' "${SSL_CONF}" > "${TEMP_FILE}" && sudo mv "${TEMP_FILE}" "${SSL_CONF}"

    # Check for exit status of awk command
    if [ $? -ne 0 ]; then
        echo "Error: awk command to add to apache server failed" >&2
        exit 1
    fi

    echo "Custom configurations added to ${SSL_CONF}"
fi

# remove temporary files
[ -f "${CONTENT_TO_INSERT}" ] && rm "${CONTENT_TO_INSERT}"
[ -f "${TEMP_FILE}" ] && rm "${TEMP_FILE}"

# Enable the SSL site
sudo a2ensite 000-default-le-ssl

# Restart Apache to apply the new configurations
sudo systemctl restart apache2

# Check if the service is running correctly
echo "Checking Apache status:"
sudo systemctl status apache2 --no-pager

echo ""
echo "Setup complete for ${HOSTNAME}"
echo ""
echo "RPC endpoint available at:"
echo "  - https://${NODE_DOMAIN}"
echo ""
echo "Note: Health checks should be configured to connect directly to port 43174"
